import sys
import time
import threading
import os
import subprocess
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QInputDialog, QFileDialog
from PyQt5.QtCore import Qt, QTimer
from qt_midi_game import MidiGame
from PyQt5.QtCore import Qt


class PomodoroGameLauncher(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()

    def initUI(self):
        self.setWindowTitle('作業・休憩・曲選択')
        self.resize(300, 200)

        layout = QVBoxLayout()

        self.start_button = QPushButton('作業・休憩時間とモード選択', self)
        self.start_button.clicked.connect(self.setup_session)
        layout.addWidget(self.start_button)

        self.setLayout(layout)

    def setup_session(self):
        # 0) モード選択
        mode, ok_mode = QInputDialog.getItem(
            self, "モード選択", "休憩に何をしたい？",
            ["音楽ゲーム", "スクリプト実行", "アプリケーション実行"],
            0,               # 初期選択インデックス
            False,           # 編集不可
            Qt.WindowStaysOnTopHint
        )
        if not ok_mode:
            return
        self.mode = mode
        
        work_min, ok1 = QInputDialog.getInt(
            self, '作業時間（分）', '作業時間（分）:', 
            25, 0, 180, 1, Qt.WindowStaysOnTopHint
        )
        work_sec, ok2 = QInputDialog.getInt(
            self, '作業時間（秒）', '作業時間（秒）:', 
            0, 0, 59, 1, Qt.WindowStaysOnTopHint
        )
        rest_min, ok3 = QInputDialog.getInt(
            self, '休憩時間（分）', '休憩時間（分）:', 
            5, 0, 180, 1, Qt.WindowStaysOnTopHint
        )
        rest_sec, ok4 = QInputDialog.getInt(
            self, '休憩時間（秒）', '休憩時間（秒）:', 
            0, 0, 59, 1, Qt.WindowStaysOnTopHint
        )
        if not (ok1 and ok2 and ok3 and ok4):
            return

        self.work_duration = work_min * 60 + work_sec
        self.rest_duration = rest_min * 60 + rest_sec
        # 1) モードごとにファイル選択
        if self.mode == "音楽ゲーム":
            dlg = QFileDialog(self, "MIDIファイルを選択")
            dlg.setNameFilter("MIDI Files (*.mid *.midi)")
            dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowStaysOnTopHint) #前面に表示
            if dlg.exec_():
                files = dlg.selectedFiles()
                if not files:
                    return
                self.midi_path = files[0]
            else:
                return
            finish_cb = self.start_game_preview
        elif self.mode == "スクリプト実行":
            dlg = QFileDialog(self, "実行する Python スクリプトを選択")
            dlg.setNameFilter("Python Files (*.py)")
            dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowStaysOnTopHint)
            if dlg.exec_():
                files = dlg.selectedFiles()
                if not files:
                    return
                self.script_path = files[0]
            else:
                return
            finish_cb = self.start_script
        else:  # EXE実行
            dlg = QFileDialog(self, "実行する EXEファイルを選択")
            dlg.setNameFilter("Executable Files (*.exe)")
            dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowStaysOnTopHint)
            if dlg.exec_():
                files = dlg.selectedFiles()
                if not files:
                    return
                self.exe_path = files[0]
            else:
                return
            finish_cb = self.start_exe
        # 2) 作業タイマー起動 → finish_cb を呼ぶ
        self.timer_win = TimerWindow(self.work_duration, finish_cb)
        self.timer_win.show()
        # 設定ウィンドウは閉じる
        self.close()
    def start_work_timer(self):
        pass

    def start_game_preview(self):
        self.game_window = MidiGame(self.midi_path, preview_mode=True)
        self.game_window.show()

        self.break_button_win = BreakButtonWindow(self.start_break_timer)
        self.break_button_win.show()

    def start_break_timer(self):
       # プレビュー解除（操作可能に）
        if hasattr(self, 'game_window'):
            self.game_window.enable_interaction()
        # 休憩タイマー開始 → 終了時に on_break_end を呼び出す
        self.timer_win = TimerWindow(self.rest_duration, self.on_break_end)
        self.timer_win.show()
    def on_break_end(self):
        """休憩終了時に呼ばれ、セッションをリスタートします"""
        # 既存のゲームウィンドウ・ボタンを閉じる
        if hasattr(self, 'game_window'):
            self.game_window.close()
        if hasattr(self, 'break_button_win'):
            self.break_button_win.close()
        # ランチャーを再表示し、再設定
        self.show()
        self.setup_session()

    def restart_cycle(self):
        """セッションを再設定するヘルパー（必要に応じて外部からも呼べます）"""
        self.show()
        self.setup_session()
    
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
    app = QApplication(sys.argv)
    launcher = PomodoroGameLauncher()
    launcher.show()
    sys.exit(app.exec_())
