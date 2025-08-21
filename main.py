import sys
import time
import threading
import os
import subprocess
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QInputDialog, QFileDialog
from PyQt5.QtCore import Qt, QTimer
from qt_midi_game import MidiGame
from PyQt5.QtCore import Qt
from qt_tetris_game import TetrisGame


class PomodoroGameLauncher(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()
                # 追加：初回の時間を保持
        self.initial_work_duration = None
        self.initial_rest_duration = None
        self.session_round = 0  # 何回目のセッションか
        
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
        # 既存ゲームウィンドウを完全クローズして属性も消す
        for name in ('game_window', 'tetris_window'):
            w = getattr(self, name, None)
            if w:
                try:
                    w.close()
                except Exception:
                    pass
            if hasattr(self, name):
                delattr(self, name)

        # 休憩ボタンも残ってたら閉じる
        if hasattr(self, 'break_button_win'):
            try:
                self.break_button_win.close()
            except Exception:
                pass
            delattr(self, 'break_button_win')



    def initUI(self):
        self.setWindowTitle('作業・休憩・曲選択')
        self.resize(300, 200)

        layout = QVBoxLayout()

        self.start_button = QPushButton('作業・休憩時間とモード選択', self)
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
        work_min, ok1 = QInputDialog.getInt(
            self, '作業時間（分）', '作業時間（分）:',
            25, 0, 180, 1, Qt.WindowStaysOnTopHint
        )
        if not ok1:
            self._cancel_to_home(); return

        work_sec, ok2 = QInputDialog.getInt(
            self, '作業時間（秒）', '作業時間（秒）:',
            0, 0, 59, 1, Qt.WindowStaysOnTopHint
        )
        if not ok2:
            self._cancel_to_home(); return

        rest_min, ok3 = QInputDialog.getInt(
            self, '休憩時間（分）', '休憩時間（分）:',
            5, 0, 180, 1, Qt.WindowStaysOnTopHint
        )
        if not ok3:
            self._cancel_to_home(); return

        rest_sec, ok4 = QInputDialog.getInt(
            self, '休憩時間（秒）', '休憩時間（秒）:',
            0, 0, 59, 1, Qt.WindowStaysOnTopHint
        )
        if not ok4:
            self._cancel_to_home(); return

        self.work_duration = work_min * 60 + work_sec
        self.rest_duration = rest_min * 60 + rest_sec
        
                # ★ここで初回の時間を保存
        if self.session_round == 0:
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
        
    def _choose_mode_and_target(self):
        # モード選択（キャンセルなら None 返す）
        mode, ok_mode = QInputDialog.getItem(
            self, "モード選択", "休憩後に何をしたい？",
            ["音楽ゲーム", "テトリス", "スクリプト実行", "EXE実行"],
            0, False, Qt.WindowStaysOnTopHint
        )
        if not ok_mode:
            return None
        self.mode = mode

        if self.mode == "音楽ゲーム":
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
        
    def _prompt_next_session(self):
        # 初回時間が無ければ通常のセットアップへ
        if self.initial_work_duration is None or self.initial_rest_duration is None:
            self.setup_session(); return

        choice, ok = QInputDialog.getItem(
            self, "次のセッション", "どうしますか？",
            ["同じ時間でもう一度", "時間を再入力", "終了"],
            0, False, Qt.WindowStaysOnTopHint
        )
        if not ok or choice == "終了":
            self.show(); self.raise_(); self.activateWindow()
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
        self.game_window = MidiGame(self.midi_path, preview_mode=True)
        self.game_window.show()

        self.break_button_win = BreakButtonWindow(self.start_break_timer)
        self.break_button_win.show()
        
    def start_tetris(self):
        """作業終了後：テトリスのプレビューを出す"""
        self._close_game_windows()
        
       
        # 半透明プレビューで立ち上げ
        self.tetris_window = TetrisGame(preview_mode=True)
        self.tetris_window.show()
        # 休憩開始ボタンを出す
        self.break_button_win = BreakButtonWindow(self.start_break_timer)
        self.break_button_win.show()

    # start_break_timer の中では既存の enable_interaction を呼んでいるので
    # テトリスも同様に操作可能になります


    def start_break_timer(self):
        gw = getattr(self, 'game_window', None)
        if gw is not None:
            gw.enable_interaction()

        tw = getattr(self, 'tetris_window', None)
        if tw is not None:
            tw.enable_interaction()

        self.timer_win = TimerWindow(self.rest_duration, self.on_break_end)
        self.timer_win.show()

    def on_break_end(self):
        # 両方まとめて確実に閉じる
        self._close_game_windows()

        if hasattr(self, 'break_button_win') and self.break_button_win:
            try:
                self.break_button_win.close()
            except Exception:
                pass
            self.break_button_win = None

        if hasattr(self, 'timer_win') and self.timer_win:
            try:
                self.timer_win.close()
            except Exception:
                pass
            self.timer_win = None

        # 次の動きを選択
        self._prompt_next_session()


    def restart_cycle(self):
        """セッションを再設定するヘルパー（必要に応じて外部からも呼べます）"""
         # ここで次の動きを選択
        self._prompt_next_session()
    
    def start_script(self):
        """作業終了後に呼ばれる：スクリプトをバックグラウンド実行"""
        # スクリプト起動
        self.proc = subprocess.Popen([sys.executable, self.script_path])
        # 休憩タイマー開始（終了時に stop_script）
        self.timer_win = TimerWindow(self.rest_duration, self.stop_script)
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
        """作業終了後に呼ばれる：EXEファイルをバックグラウンド実行"""
        self.proc = subprocess.Popen([self.exe_path])
        # 休憩タイマー開始（終了時に stop_exe を呼ぶ）
        self.timer_win = TimerWindow(self.rest_duration, self.stop_exe)
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
    def __init__(self, duration, on_finish=None):
        super().__init__()
        self.duration = duration
        self.on_finish = on_finish
        self.start_time = time.time()
        self.initUI()

    def initUI(self):
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint |
            Qt.WindowTitleHint |
            Qt.WindowCloseButtonHint
        )
        # ウィンドウサイズを固定
        self.resize(200, 60)
        # 画面右上に移動（マージン10px）
        screen_rect = QApplication.primaryScreen().availableGeometry()
        x = screen_rect.width() - self.width() - 10
        y = screen_rect.top() + 10
        self.move(x, y)
        self.label = QLabel("", self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("font-size: 24px;")

        layout = QVBoxLayout()
        layout.addWidget(self.label)
        self.setLayout(layout)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_timer)
        self.timer.start(1000)

    def update_timer(self):
        elapsed = int(time.time() - self.start_time)
        remaining = self.duration - elapsed
        if remaining <= 0:
            self.timer.stop()
            self.close()
            if self.on_finish:
                self.on_finish()
            return
        minutes = remaining // 60
        seconds = remaining % 60
        self.label.setText(f"{minutes:02}:{seconds:02}")

class BreakButtonWindow(QWidget):
    def __init__(self, start_break_callback):
        super().__init__()
        # 常に最前面に表示
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        # ボタン作成＆サイズ固定
        self.button = QPushButton('休憩を開始する', self)
        self.button.clicked.connect(start_break_callback)
        self.button.clicked.connect(self.close)
        self.button.resize(150, 50)
        self.setFixedSize(self.button.size())
        # 画面の右上へ移動
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.width() - self.width() - 10
        y = 10
        self.move(x, y)


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

if __name__ == '__main__':
    app = QApplication(sys.argv) # ← 追加
    app.setQuitOnLastWindowClosed(False)
    launcher = PomodoroGameLauncher()
    launcher.show()
    sys.exit(app.exec_())
