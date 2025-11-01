import sys
import time
import threading
import os
import random
import subprocess
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QInputDialog, QFileDialog
from PyQt5.QtCore import Qt, QTimer,QObject
from qt_midi_game import MidiGame
from PyQt5.QtCore import Qt
from qt_tetris_game import TetrisGame
from PyQt5.QtGui import QGuiApplication, QCursor

def win_force_topmost(widget, on=True):
    try:
        import ctypes, sys
        if sys.platform != "win32":
            return
        hwnd = int(widget.winId())
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        user32 = ctypes.windll.user32
        # 位置は変えずに「最前面/解除」だけ切替
        SWP_NOMOVE=0x2; SWP_NOSIZE=0x1; SWP_NOACTIVATE=0x10; SWP_SHOWWINDOW=0x40
        HWND_TOPMOST=-1; HWND_NOTOPMOST=-2
        user32.SetWindowPos(
            hwnd,
            HWND_TOPMOST if on else HWND_NOTOPMOST,
            0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW
        )
    except Exception:
        pass

def force_to_screen(widget: QWidget, screen):
    """widget を強制的に screen 側に割り当て＆左上に移動"""
    widget.setAttribute(Qt.WA_NativeWindow, True)
    widget.winId()
    h = widget.windowHandle()
    if h and screen:
        h.setScreen(screen)
    g = screen.geometry()
    widget.move(g.topLeft())

class PreviewController(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._owner = parent
        self._timer = None
        self._widget = None
        self._step = 0.0
        self._target = 1.0
        # ここから追加：他画面ホワイトアウト
        # ↓ 白オーバーレイ用（これがないと AttributeError）
        self._whiteouts = []
        self._white_timer = None
        self._white_keepalive = None  # ← 最前面維持タイマー
        self._front_keepalive = None   # ← 追加：ゲーム窓の押し上げタイマー



    # PreviewController.start を置き換え
    def start(self, widget, *, start_opacity=0.1, end_opacity=0.7,
            duration_ms=30000, interval_ms=200, fullscreen=None, screen=None,
            input_through=True):
        self.stop()
        self._widget = widget
        was_full = widget.isFullScreen()

        # 先にネイティブ化
        widget.setAttribute(Qt.WA_NativeWindow, True)
        widget.winId()

        # ← ここをゲーム側の共通関数に委譲
        if input_through and hasattr(widget, "set_click_through"):
            widget.set_click_through(True)
        else:
            # フォールバック（旧処理）
            widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            f = widget.windowFlags()
            f |= Qt.FramelessWindowHint | Qt.WindowTransparentForInput | Qt.WindowStaysOnTopHint | Qt.Tool
            widget.setWindowFlags(f)

        widget.setWindowOpacity(float(start_opacity))

        if fullscreen is None:
            fullscreen = was_full
        (widget.showFullScreen() if fullscreen else widget.show())

        # 表示後にスクリーンを確実に合わせる（ここでハンドル再生成される事がある）
        if screen is not None:
            try:
                force_to_screen(widget, screen)
            except Exception:
                pass

        # 表示後にもう一度“念押し”でクリック透過を適用
                # 表示後に“念押し”でクリック透過と最前面を再適用
        QTimer.singleShot(0, lambda: (
            hasattr(widget, "set_click_through") and widget.set_click_through(True)
        ))
        QTimer.singleShot(0, lambda: win_force_topmost(widget, True))
        
         # ← 追加：ゲーム窓の最前面 Keep-Alive（タイマーより遅く）
        # if self._front_keepalive:
        #     try: self._front_keepalive.stop()
        #     except Exception: pass
        # self._front_keepalive = QTimer(self)
        # self._front_keepalive.timeout.connect(lambda: (widget.raise_(), win_force_topmost(widget, True)))
        # self._front_keepalive.start(1200)

        # あとはフェード
        steps = max(1, int(duration_ms / float(interval_ms)))
        self._target = float(end_opacity)
        self._step = (self._target - float(start_opacity)) / steps
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(int(interval_ms))





    def _tick(self):
        w = self._widget
        if not w:
            self.stop(); return
        op = float(w.windowOpacity()) + self._step
        if (self._step >= 0 and op >= self._target) or (self._step < 0 and op <= self._target):
            w.setWindowOpacity(self._target)
            self.stop()
            return
        w.setWindowOpacity(op)

    def finalize(self):
        if not self._widget:
            return
        self.stop()
        w = self._widget
        w.setWindowOpacity(1.0)

        # ★ 透過を解除
        w.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        flags = w.windowFlags()
        flags &= ~Qt.WindowTransparentForInput
        flags &= ~Qt.FramelessWindowHint
        flags |= Qt.Window
        w.setWindowFlags(flags)
        w.showFullScreen()
        try:
            from qt_midi_game import MidiGame
            if isinstance(w, MidiGame):
                w.set_click_through(False)   # 透過解除＋TopMost維持
        except Exception:
            pass
        win_force_topmost(w, True)  
        
        self._widget = None
        win_force_topmost(w, True)
        
        if self._front_keepalive:
            try: self._front_keepalive.stop()
            except Exception: pass
        self._front_keepalive = None


    def stop(self):
        if self._timer:
            try: self._timer.stop()
            except Exception: pass
        self._timer = None
    
    def start_whiteout_others(self, host_widget=None, *, host_screen=None,
                            include_host=False, start_opacity=0.0, end_opacity=0.7,
                            duration_ms=30000, interval_ms=200):
        self.stop_whiteout_others()

        screens = QGuiApplication.screens()
        if not screens:
            return
        # 親（タイマー用）を最初に決めておく
        p = self.parent()
        parent_for_timer = (p if isinstance(p, QWidget) else host_widget) or self

        # ★ ホスト画面は明示で受け取る（無い場合だけ推定）
        if host_screen is None and host_widget is not None:
            wh = host_widget.windowHandle()
            if wh and wh.screen():
                host_screen = wh.screen()
            else:
                center = host_widget.frameGeometry().center()
                host_screen = QGuiApplication.screenAt(center)
        if host_screen is None:
            host_screen = QGuiApplication.primaryScreen()

        steps = max(1, duration_ms // interval_ms)
        step = (float(end_opacity) - float(start_opacity)) / steps

        for sc in screens:
            if not include_host and sc is host_screen:
                continue

            ov = QWidget(None,
                    Qt.Window |
                    Qt.FramelessWindowHint |
                    Qt.WindowStaysOnTopHint |
                    Qt.WindowTransparentForInput     # ← クリック透過
            )
            ov.setAttribute(Qt.WA_TransparentForMouseEvents, True)  # ← 念のため（Qt版クリック透過）
            ov.setAttribute(Qt.WA_NativeWindow, True)
            ov.setAttribute(Qt.WA_ShowWithoutActivating, True)
            ov.setFocusPolicy(Qt.NoFocus)
            ov.setStyleSheet("background:#ffffff;")

            # まず仮表示でハンドル作る
            g = sc.geometry()
            ov.move(g.topLeft())
            ov.resize(g.size())
            ov.show()

            wh = ov.windowHandle()
            if wh and wh.screen() is not sc:
                wh.setScreen(sc)

            ov.hide()
            ov.setWindowOpacity(float(start_opacity))
            ov.showFullScreen()
            ov.raise_()
            win_force_topmost(ov, True)  

            self._whiteouts.append((ov, step, float(end_opacity)))

        if self._whiteouts:
            # ★ ここがポイント：QObject.parent() を呼ぶ（上書きしていないのでOK）
            p = self.parent()
            parent_for_timer = p if isinstance(p, QWidget) else host_widget
            self._white_timer = QTimer(parent_for_timer or self)
            self._white_timer.timeout.connect(self._tick_whiteouts)
            self._white_timer.start(interval_ms)
        if self._white_keepalive:
            try: self._white_keepalive.stop()
            except Exception: pass
            self._white_keepalive = None

        self._white_keepalive = QTimer(parent_for_timer)
        self._white_keepalive.timeout.connect(self._bump_whiteouts_on_top)
        self._white_keepalive.start(1000)  # 1秒に1回で十分
        
    def _bump_whiteouts_on_top(self):
        # 可視なら定期的に最前面へ
        for (ov, _, _) in list(self._whiteouts):
            try:
                if ov and ov.isVisible():
                    ov.raise_()
            except Exception:
                pass


    def _tick_whiteouts(self):
        keep = []
        for (ov, step, target) in self._whiteouts:
            if ov is None or not ov.isVisible():
                continue
            op = float(ov.windowOpacity()) + step
            # 目標到達でピタッと止める
            if (step >= 0 and op >= target - 1e-6) or (step < 0 and op <= target + 1e-6):
                ov.setWindowOpacity(target)
                keep.append((ov, step, target))
            else:
                ov.setWindowOpacity(op)
                keep.append((ov, step, target))
        self._whiteouts = keep
        # 全部到達したらタイマー停止（任意）
        if self._white_timer and all(abs(ov.windowOpacity() - tgt) < 1e-6 for (ov, _, tgt) in self._whiteouts):
            try: self._white_timer.stop()
            except Exception: pass
            self._white_timer = None

    def stop_whiteout_others(self):
        if self._white_timer:
            try: self._white_timer.stop()
            except Exception: pass
            self._white_timer = None
        for (ov, _, _) in self._whiteouts:
            try: ov.close()
            except Exception: pass
        self._whiteouts.clear()
        if self._white_keepalive:
            try: self._white_keepalive.stop()
            except Exception: pass
            self._white_keepalive = None
    def _bump_on_top(self):
        if not self.isVisible(): return
        self.raise_()
        win_force_topmost(self, True)

# （他の QWidget クラス定義の近くに追加）

class FinishBreakWindow(QWidget):
    def __init__(self, title, on_confirm, screen=None, parent=None):
        super().__init__(parent)
        self._screen = screen
        self._on_confirm = on_confirm

        # 閉じさせず常時最前面（×は出すなら closeEvent で握りつぶす）
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        btn = QPushButton("休憩終了（実行中の処理を停止）", self)
        btn.setStyleSheet("font-size: 24px; padding: 12px 16px;")
        btn.clicked.connect(self._handle_confirm)

        lay = QVBoxLayout(self)
        lay.addWidget(btn)
        self.setLayout(lay)
        self.setFixedSize(420, 120)

        # 表示位置：指定スクリーン右上
        scr = self._screen or (self.parent().windowHandle().screen() if self.parent() and self.parent().windowHandle() else None)
        scr = scr or QGuiApplication.primaryScreen()
        g = scr.availableGeometry()
        self.move(g.right() - self.width() - 12, g.top() + 12)

        # 念押しで最前面キープ（穏やかに）
        self._ontop = QTimer(self)
        self._ontop.setTimerType(Qt.VeryCoarseTimer)
        self._ontop.timeout.connect(self.raise_)
        self._ontop.start(1000)

    def _handle_confirm(self):
        try:
            if callable(self._on_confirm):
                self._on_confirm()
        finally:
            self.close()

    def closeEvent(self, e):
        # ×を押しても閉じないで最前に戻すなら以下の2行を有効化
        # e.ignore()
        # QTimer.singleShot(0, self.raise_)
        # → 今回は閉じてもよい運用にしておく
        try:
            if hasattr(self, "_ontop") and self._ontop:
                self._ontop.stop()
        except Exception:
            pass
        super().closeEvent(e)




class PomodoroGameLauncher(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()
                # 追加：初回の時間を保持
        self.initial_work_duration = None
        self.initial_rest_duration = None
        self.session_round = 0  # 何回目のセッションか
        self.preview=PreviewController(parent=self)
        
    def _shutdown_all(self):
        """終了時の後始末を一箇所に集約"""
        # すべてのゲーム・プレビューを閉じる
        self._close_game_windows()

        # タイマー/休憩ボタンも閉じる
        for name in ('timer_win', 'break_button_win'):
            w = getattr(self, name, None)
            if w:
                try: w.close()
                except Exception: pass
                setattr(self, name, None)

        # 起動中の外部プロセスがあれば終了
        if hasattr(self, 'proc') and self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=3)
            except Exception:
                try: self.proc.kill()
                except Exception: pass
            self.proc = None
        if hasattr(self, 'preview') and self.preview:
            self.preview.stop_whiteout_others()
            self.preview.stop()
    # PomodoroGameLauncher 内（メソッドのどこかに追加）

    def _confirm_stop_runner(self, kind: str):
        """FinishBreakWindow のボタンで呼ばれる停止実行ヘルパ"""
        try:
            if kind == "script":
                self.stop_script()   # 既存：通知→restart_cycle までやる
            elif kind == "exe":
                self.stop_exe()      # 既存：通知→restart_cycle までやる
        except Exception:
            pass


    def closeEvent(self, e):
        """×が押されたらアプリ全体を終了。コードからの close() は終了しない。"""
        if e.spontaneous():                # ユーザが×/Alt+F4/OS閉じる など
            self._shutdown_all()
            e.accept()
            QApplication.instance().quit() # ここで完全終了
        else:
            e.accept()                     # プログラム起因の close() は単に閉じるだけ
    
        
    def _cancel_to_home(self):
        # 一時状態をクリア（残っていても害はないけど念のため）
        for attr in ('mode','work_duration','rest_duration','midi_path','script_path','exe_path'):
            if hasattr(self, attr):
                try:
                    delattr(self, attr)
                except Exception:
                    pass
        # ランチャーを前面に出す
        self.show()
        self.raise_()
        self.activateWindow()
        
# PomodoroGameLauncher 内に追加
    def _close_game_windows(self):
        # プレビュー停止（残っていたら）
        if hasattr(self, 'preview') and self.preview:
            self.preview.stop()

        for name in ('game_window', 'tetris_window'):
            w = getattr(self, name, None)
            if w:
                try:
                    w.close()
                except Exception:
                    pass
            if hasattr(self, name):
                delattr(self, name)

        if hasattr(self, 'break_button_win'):
            try:
                self.break_button_win.close()
            except Exception:
                pass
            delattr(self, 'break_button_win')
            
    from PyQt5.QtWidgets import QInputDialog  # 既にimport済みならOK

    # 大きめの整数入力ダイアログ
    def _big_get_int(self, title, label, default=0, minimum=0, maximum=999, step=1):
        dlg = QInputDialog(self)
        dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowStaysOnTopHint)
        dlg.setInputMode(QInputDialog.IntInput)
        dlg.setWindowTitle(title)
        dlg.setLabelText(label)
        dlg.setIntRange(minimum, maximum)
        dlg.setIntStep(step)
        dlg.setIntValue(default)

        # 約2倍サイズ＆フォント
        dlg.resize(480, 220)
        dlg.setStyleSheet("""
            QInputDialog { font-size: 24px; }
            QLabel       { font-size: 28px; }
            QSpinBox     { font-size: 28px; min-height: 44px; min-width: 140px; }
            QPushButton  { font-size: 24px; padding: 8px 16px; }
        """)

        ok = dlg.exec_()
        return dlg.intValue(), bool(ok)

    def _big_get_item(self, title, label, items, current_index=0, editable=False):
        from PyQt5.QtWidgets import QInputDialog

        dlg = QInputDialog(self)
        dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowStaysOnTopHint)
        dlg.setWindowTitle(title)
        dlg.setLabelText(label)

        # コンボボックスを使うモードにする（内部的には TextInput 扱い）
        dlg.setInputMode(QInputDialog.TextInput)
        dlg.setOption(QInputDialog.UseListViewForComboBoxItems, True)
        dlg.setComboBoxItems(items)
        dlg.setComboBoxEditable(editable)

        # ここがポイント：既定値はインデックスではなく「文字列」で指定する
        if 0 <= current_index < len(items):
            dlg.setTextValue(items[current_index])
        elif items:
            dlg.setTextValue(items[0])
        else:
            dlg.setTextValue("")

        # 大きめサイズ＆フォント
        dlg.resize(520, 300)
        dlg.setStyleSheet("""
            QInputDialog { font-size: 24px; }
            QLabel       { font-size: 28px; }
            QComboBox    { font-size: 28px; min-height: 44px; min-width: 280px; }
            QListView    { font-size: 28px; }
            QPushButton  { font-size: 24px; padding: 8px 16px; }
        """)

        ok = dlg.exec_()
        return dlg.textValue(), bool(ok)
    # 画面選択の補助（ランチャーのメソッドとして）
    def _target_screen(self):
        h = self.windowHandle()
        s = h.screen() if h else None
        if not s:
            from PyQt5.QtGui import QGuiApplication, QCursor
            s = QGuiApplication.screenAt(QCursor.pos())
        return s or QGuiApplication.primaryScreen()
    # PomodoroGameLauncher 内に追加
    def _start_return_to_work_fade(self, remaining_sec=60):
        # どのウィンドウをフェードさせるか（音ゲー優先、なければテトリス）
        w = getattr(self, 'game_window', None) or getattr(self, 'tetris_window', None)
        if not w:
            return

        # 残り時間が60秒未満なら、その分だけでフェード（割り込み再生でもOK）
        duration_ms = max(1, int(remaining_sec) * 1000)

        scr = self._target_screen()
        # 1.0 → 0.1 へ ふわっと透明化。入力は作業側へ通す（True）。
        self.preview.start(
            w,
            start_opacity=float(w.windowOpacity()) if w.isVisible() else 1.0,
            end_opacity=0.1,
            duration_ms=duration_ms,
            interval_ms=200,
            fullscreen=True,
            screen=scr,
            input_through=True
        )







    def initUI(self):
        self.setWindowTitle('作業・休憩・モード選択')
        self.resize(600, 400)

        layout = QVBoxLayout()

        self.start_button = QPushButton('作業・休憩時間とモード選択', self)
        self.start_button.setStyleSheet("font-size: 32px;") 
        self.start_button.clicked.connect(self.setup_session)
        layout.addWidget(self.start_button)

        self.setLayout(layout)
        # ★追加：キャンセル時に初期画面へ戻す共通処理
    def _cancel_to_home(self):
        # 一時状態をクリア（残っていても害はないけど念のため）
        for attr in ('mode','work_duration','rest_duration','midi_path','script_path','exe_path'):
            if hasattr(self, attr):
                try:
                    delattr(self, attr)
                except Exception:
                    pass
        # ランチャーを前面に出す
        self.show()
        self.raise_()
        self.activateWindow()

    def setup_session(self):
        self._close_game_windows()

        # 時間入力
        # work_min, ok1 = QInputDialog.getInt(... を置き換え）
        work_min, ok1 = self._big_get_int('作業時間（分）', '作業時間（分）:', 0, 0, 180, 1)
        if not ok1: self._cancel_to_home(); return

        work_sec, ok2 = self._big_get_int('作業時間（秒）', '作業時間（秒）:', 1, 0, 59, 1)
        if not ok2: self._cancel_to_home(); return

        rest_min, ok3 = self._big_get_int('休憩時間（分）', '休憩時間（分）:', 5, 0, 180, 1)
        if not ok3: self._cancel_to_home(); return

        rest_sec, ok4 = self._big_get_int('休憩時間（秒）', '休憩時間（秒）:', 0, 0, 59, 1)
        if not ok4: self._cancel_to_home(); return

        self.work_duration = work_min * 60 + work_sec
        self.rest_duration = rest_min * 60 + rest_sec
        
                # ★ここで初回の時間を保存
        #if self.session_round == 0:
        self.initial_work_duration = self.work_duration
        self.initial_rest_duration = self.rest_duration
        self.session_round += 1
        
       # ↓↓↓ 以下は「モード選択＆ファイル選択」部分を関数化して呼ぶように変更
        finish_cb = self._choose_mode_and_target()
        if not finish_cb:
            self._cancel_to_home(); return

        self.timer_win = TimerWindow(self.work_duration, finish_cb)
        self.timer_win.show()
        self.hide()
        
    # 追加：デモ用に .mid / .midi を自動選曲
    def _find_demo_midi(self):
        # 1) 環境変数が指定されていたら最優先
        p = os.environ.get("45秒で何ができる")
        if p and os.path.isfile(p):
            return p

        # 2) このスクリプトとカレントの 'music' を探す
        candidates = []
        for folder in (os.path.join(os.path.dirname(__file__), "music"),
                       os.path.join(os.getcwd(), "music")):
            if os.path.isdir(folder):
                for name in os.listdir(folder):
                    if name.lower().endswith((".mid", ".midi")):
                        candidates.append(os.path.join(folder, name))

        if candidates:
            try:
                return candidates[0]   # デモはランダム
            except Exception:
                return candidates[0]              # 念のため先頭

        # 3) 見つからなければプロジェクト配下をざっと探索（最初に見つかった1件）
        for root, _, files in os.walk(os.path.dirname(__file__)):
            for name in files:
                if name.lower().endswith((".mid", ".midi")):
                    return os.path.join(root, name)

        return None
        
        
    def _choose_mode_and_target(self):
        # モード選択（キャンセルなら None 返す）
        # mode, ok_mode = QInputDialog.getItem(... を置き換え）
        mode, ok_mode = self._big_get_item(
            "モード選択", "休憩後に何をしたい？",
            ["音楽ゲーム", "テトリス", "スクリプト実行", "EXE実行"], 0, False
        )
        if not ok_mode: return None
        self.mode = mode


        if self.mode == "音楽ゲーム":
            auto = self._find_demo_midi()
            if auto:
                self.midi_path = auto
                print(f"{self.midi_path}")
                return self.start_game_preview
            
            dlg = QFileDialog(self, "MIDIファイルを選択")
            dlg.setNameFilter("MIDI Files (*.mid *.midi)")
            dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowStaysOnTopHint)
            if dlg.exec_():
                files = dlg.selectedFiles()
                if not files: return None
                self.midi_path = files[0]
            else:
                return None
            return self.start_game_preview

        elif self.mode == "テトリス":
            return self.start_tetris

        elif self.mode == "スクリプト実行":
            dlg = QFileDialog(self, "実行する Python スクリプトを選択")
            dlg.setNameFilter("Python Files (*.py)")
            dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowStaysOnTopHint)
            if dlg.exec_():
                files = dlg.selectedFiles()
                if not files: return None
                self.script_path = files[0]
            else:
                return None
            return self.start_script

        else:  # EXE実行
            dlg = QFileDialog(self, "実行する EXEファイルを選択")
            dlg.setNameFilter("Executable Files (*.exe)")
            dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowStaysOnTopHint)
            if dlg.exec_():
                files = dlg.selectedFiles()
                if not files: return None
                self.exe_path = files[0]
            else:
                return None
            return self.start_exe
        
        # PomodoroGameLauncher 内
    def _really_quit(self):
        # まだ残ってるタイマーやゲーム窓を確実に閉じる
        try:
            if hasattr(self, 'timer_win') and self.timer_win:
                self.timer_win.close()
        except Exception:
            pass
        self._close_game_windows()

        # バックグラウンド起動中のスクリプト/EXEがあれば止める
        if hasattr(self, 'proc'):
            try:
                self.proc.terminate()
                self.proc.wait(timeout=3)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass

        # アプリを終了
        QApplication.instance().quit()

        
    def _prompt_next_session(self):
        # 初回時間が無ければ通常のセットアップへ
        if self.initial_work_duration is None or self.initial_rest_duration is None:
            self.setup_session(); return

        choice, ok = self._big_get_item(
            "次のセッション", "どうしますか？",
            ["同じ時間でもう一度", "時間を再入力", "終了"], 0, False
        )
        if not ok or choice == "終了":
            self._really_quit()
            return

        if choice.startswith("同じ時間"):
            # 初回の時間をそのまま使用。モード/ファイルは選ばせる
            self.work_duration = self.initial_work_duration
            self.rest_duration = self.initial_rest_duration

            finish_cb = self._choose_mode_and_target()
            if not finish_cb:
                self._cancel_to_home(); return

            self.timer_win = TimerWindow(self.work_duration, finish_cb)
            self.timer_win.show()
            self.close()
        else:
            # 時間を再入力（最初から）
            self.setup_session()




 
    def start_work_timer(self):
        pass

    def start_game_preview(self):
        self._close_game_windows()
        # ここを preview_mode=False に
        self.game_window = MidiGame(self.midi_path, preview_mode=False)
        # self.game_window.showFullScreen()
        
        scr = self._target_screen()  # ★ ランチャーのいる画面
        # プレビュー（全画面・フェード）
        self.preview.start(self.game_window, fullscreen=True,screen=scr)
    # ★ ゲーム以外のすべての画面を白でフェード
        self.preview.start_whiteout_others(self.game_window,  host_screen=scr,include_host=False,)
        scr = self._target_screen()

        self.break_button_win = BreakButtonWindow(
            self.start_break_timer,
            on_manual_close=self._really_quit,
            screen=scr,                 # ← これ追加
            parent=self                 # （任意）親つけると管理が安定
        )
        self.break_button_win.show()
        self.break_button_win.raise_()    # タイマーを前面へ

        
    def start_tetris(self):
        self._close_game_windows()
        # ここを preview_mode=False に
        self.tetris_window = TetrisGame(preview_mode=False)
        # self.tetris_window.showFullScreen()
        scr = self._target_screen()  # ★ ランチャーのいる画面
        # プレビュー（全画面・フェード）
        self.preview.start(self.tetris_window, fullscreen=True,screen=scr)
        # ★ ゲーム以外のすべての画面を白でフェード
        self.preview.start_whiteout_others(self.tetris_window,  host_screen=scr,include_host=False,)
        scr = self._target_screen()

        self.break_button_win = BreakButtonWindow(
            self.start_break_timer,
            on_manual_close=self._really_quit,
            screen=scr,                 # ← これ追加
            parent=self                 # （任意）親つけると管理が安定
        )
        self.break_button_win.show()
        self.break_button_win.raise_()


    # start_break_timer の中では既存の enable_interaction を呼んでいるので
    # テトリスも同様に操作可能になります


    def start_break_timer(self):
        # プレビュー終了→操作可へ
        self.preview.finalize()
        scr = self._target_screen()  # ★ ランチャーのいる画
            # 既存の白オーバーレイがあれば一旦消す
        try:
            self.preview.stop_whiteout_others()
        except Exception:
            pass

        gw = getattr(self, 'game_window', None)
        if gw is not None:
            # ゲーム側はフォーカス確保など最小限
            try:
                gw.enable_interaction()
            except Exception:
                pass

        tw = getattr(self, 'tetris_window', None)
        if tw is not None:
            try:
                tw.enable_interaction()
            except Exception:
                pass
            
            # どのウィンドウをホストにするか（音ゲー優先、なければテトリス）
        host = getattr(self, 'game_window', None) or getattr(self, 'tetris_window', None)

        # 他モニターを“即”100%白に（フェードなし）
        # start_opacity=end_opacity=1.0 かつ duration_ms=1 で瞬時に白
        self.preview.start_whiteout_others(
            host_widget=host,
            include_host=False,
            start_opacity=1.0,
            end_opacity=1.0,
            duration_ms=1,
            interval_ms=50
        )

        self.timer_win = TimerWindow(
        self.rest_duration,
        self.on_break_end,
        screen=scr,
        one_minute_cb=self._start_return_to_work_fade)
        self.timer_win.show()
        self.timer_win.raise_()  # 常に最前面


    def on_break_end(self):
        # 他画面白オーバーレイを消す（既存）
        try:
            self.preview.stop_whiteout_others()
        except Exception:
            pass

        # ゲーム窓を閉じる（既存）
        self._close_game_windows()

        if hasattr(self, 'break_button_win') and self.break_button_win:
            try:
                self.break_button_win.close()
            except Exception:
                pass
            self.break_button_win = None

        # ★ ここから分岐：exe/script のときは「休憩終了」ボタンで停止させる
        scr = self._target_screen()

        if getattr(self, "mode", "") == "スクリプト実行" and getattr(self, "proc", None):
            # 停止確認ボタン表示 → 押されたら self.stop_script()
            self.finish_break_win = FinishBreakWindow(
                "休憩終了",
                on_confirm=lambda: self._confirm_stop_runner("script"),
                screen=scr,
                parent=self
            )
            self.finish_break_win.show()
            return

        if getattr(self, "mode", "") == "EXE実行" and getattr(self, "proc", None):
            # 停止確認ボタン表示 → 押されたら self.stop_exe()
            self.finish_break_win = FinishBreakWindow(
                "休憩終了",
                on_confirm=lambda: self._confirm_stop_runner("exe"),
                screen=scr,
                parent=self
            )
            self.finish_break_win.show()
            return

        # ★ それ以外（音ゲー/テトリス等）は従来どおり次の動きへ
        self._prompt_next_session()



    def restart_cycle(self):
        """セッションを再設定するヘルパー（必要に応じて外部からも呼べます）"""
         # ここで次の動きを選択
        self._prompt_next_session()
    
    def start_script(self):
        self.proc = subprocess.Popen([sys.executable, self.script_path])
        scr = self._target_screen()
        self.timer_win = TimerWindow(self.rest_duration, self.on_break_end, screen=scr)
        self.timer_win.show()




    def stop_script(self):
        """休憩終了後に呼ばれる：起動中のスクリプトを停止"""
        if hasattr(self, 'proc'):
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        # 完了通知
        notice = QLabel("休憩終了！スクリプトを停止しました。")
        notice.setWindowFlags(Qt.WindowStaysOnTopHint)
        notice.setAlignment(Qt.AlignCenter)
        notice.setStyleSheet("font-size:18px;padding:10px;")
        notice.show()
        def finish_notice():
            notice.close()
            self.restart_cycle()
        QTimer.singleShot(3000, finish_notice)
    def start_exe(self):
        self.proc = subprocess.Popen([self.exe_path])
        scr = self._target_screen()
        self.timer_win = TimerWindow(self.rest_duration, self.on_break_end, screen=scr)
        self.timer_win.show()

    def stop_exe(self):
        """休憩終了後に呼ばれる：起動中の EXE を停止"""
        if hasattr(self, 'proc'):
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        # 完了通知とセッション再スタート
        notice = QLabel("休憩終了！EXEを停止しました。")
        notice.setWindowFlags(Qt.WindowStaysOnTopHint)
        notice.setAlignment(Qt.AlignCenter)
        notice.setStyleSheet("font-size:18px;padding:10px;")
        notice.show()
        def finish_notice():
            notice.close()
            self.restart_cycle()
        QTimer.singleShot(3000, finish_notice)

class TimerWindow(QWidget):
    def __init__(self, duration, on_finish=None,exit_on_manual_close=True,screen=None,parent=None,one_minute_cb=None):
        super().__init__(parent)
        self.duration = duration
        self.on_finish = on_finish
        self._screen = screen  
        self.exit_on_manual_close = exit_on_manual_close # ← 追加：手動クローズなら終了する？
        self._closing_programmatically = False    
        self._one_minute_cb = one_minute_cb        # ← 追加
        self._one_minute_fired = False     
        self.start_time = time.time()
        self.initUI()

    def initUI(self):
        # TimerWindow.__init__ の initUI でフラグをこれに
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowTitleHint | Qt.WindowCloseButtonHint
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)  # 表示してもフォーカスは奪わない
        
        
        # ★ 指定スクリーンの右上
        scr = self._screen or (self.parent().windowHandle().screen() if self.parent() and self.parent().windowHandle() else None)
        scr = scr or QGuiApplication.primaryScreen()
        g = scr.availableGeometry()

        # ウィンドウサイズを固定
        self.resize(400, 120)
        # 画面右上に移動（マージン10px）
        screen_rect = QApplication.primaryScreen().availableGeometry()
        x = g.right() - self.width() - 10
        y = g.top() + 10
        self.move(x, y)
        self.label = QLabel("", self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("font-size: 48px;")

        layout = QVBoxLayout()
        layout.addWidget(self.label)
        self.setLayout(layout)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_timer)
        self.timer.start(1000)
        # TimerWindow クラスに追記（フォーカスを奪わず最前面へ“押し上げ”）
         # ★ 常時“最前面に押し上げ”キープ（0.8秒おき）
        self._ontop_timer = QTimer(self)
        self._ontop_timer.setTimerType(Qt.VeryCoarseTimer)
        self._ontop_timer.timeout.connect(self._bump_on_top)
        self._ontop_timer.start(800)
    def showEvent(self, e):
        super().showEvent(e)
        self._bump_on_top()

    def _bump_on_top(self):
        if not self.isVisible():
            return
        # フォーカスは奪わずに最前面へ
        self.raise_()
        win_force_topmost(self, True)   # ← これを追加


    def update_timer(self):
        elapsed = int(time.time() - self.start_time)
        remaining = self.duration - elapsed
        
        # 残り1分になった瞬間に一度だけ呼ぶ（60秒未満の休憩なら即呼ぶ）
        if (not self._one_minute_fired) and (remaining <= 60):
            self._one_minute_fired = True
            if callable(self._one_minute_cb):
                try:
                    self._one_minute_cb(max(remaining, 0))  # 残り秒数を渡す
                except Exception:
                    pass
                
        if remaining <= 0:
            self.timer.stop()
            if self.on_finish:
                self.on_finish()
            self._closing_programmatically = True
            self.close()
            return
        minutes = remaining // 60
        seconds = remaining % 60
        self.label.setText(f"{minutes:02}:{seconds:02}")
        
    def closeEvent(self, e):
        if hasattr(self, "_ontop_timer") and self._ontop_timer:
            try: self._ontop_timer.stop()
            except Exception: pass
        if not self._closing_programmatically and self.exit_on_manual_close:
            QApplication.quit()
        super().closeEvent(e)

class BreakButtonWindow(QWidget):
    def __init__(self, start_break_callback,on_manual_close=None,screen=None,parent=None):
        super().__init__(parent)
        self._screen = screen  # ★ 追加
        # 常に最前面に表示
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.on_manual_close = on_manual_close  # ← 追加: 手動クローズ時の処理（クリーンアップ→終了）
        self._closed_by_button = False
        # ボタン作成＆サイズ固定
        self.button = QPushButton('休憩を開始する', self)
        self.button.clicked.connect(start_break_callback)
        self.button.clicked.connect(self.close)
        self.button.setStyleSheet("""
            font-size: 28px;      /* ここで大きさ調整。32px 等にしてもOK *//* ボタンの余白も広げる */
        """)
        self.button.resize(300, 100)
        self.setFixedSize(self.button.size())

        # ★ 指定スクリーンの右上へ
        scr = self._screen or (self.parent().windowHandle().screen() if self.parent() and self.parent().windowHandle() else None)
        scr = scr or QGuiApplication.primaryScreen()
        g = scr.availableGeometry()
        self.move(g.right() - self.width() - 10, g.top() + 10)
        
        # __init__ の keep-alive を置き換え
        self._ontop_timer = QTimer(self)
        self._ontop_timer.setTimerType(Qt.VeryCoarseTimer)
        self._ontop_timer.timeout.connect(lambda: (self.raise_(), win_force_topmost(self, True)))  # ← ここ変更
        self._ontop_timer.start(800)

    def showEvent(self, e):
        super().showEvent(e)
        self.raise_()
        win_force_topmost(self, True)   # ← これも追加



    def initUI(self):
        self.setWindowTitle("休憩開始")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.WindowTitleHint)
        self.resize(200, 100)
        layout = QVBoxLayout()
        self.button = QPushButton("休憩を開始する", self)
        self.button.clicked.connect(self.start_break)
        layout.addWidget(self.button)

        self.setLayout(layout)

    def start_break(self):
        self.on_start_break()
        self.close()
        

        
    def _on_button_clicked(self):
        # ボタンで閉じるときは終了しない
        self._closed_by_button = True
        try:
            self._start_break_cb()
        finally:
            self.close()

    def closeEvent(self, e):
        if hasattr(self, "_ontop_timer") and self._ontop_timer:
            try: self._ontop_timer.stop()
            except Exception: pass
        if (e.spontaneous() and not self._closed_by_button):
            if callable(self.on_manual_close):
                self.on_manual_close()
            else:
                QApplication.quit()
        super().closeEvent(e)

if __name__ == '__main__':
    app = QApplication(sys.argv) # ← 追加
    app.setQuitOnLastWindowClosed(False)
    launcher = PomodoroGameLauncher()
    launcher.show()
    sys.exit(app.exec_())
