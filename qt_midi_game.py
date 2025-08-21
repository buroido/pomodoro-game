import sys
import time
import random
import threading
import os
from collections import defaultdict

import mido
import pygame
import pygame.midi

from PyQt5.QtWidgets import (
    QApplication, QWidget, QGraphicsView, QGraphicsScene, QGraphicsRectItem,
    QPushButton, QFileDialog
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QBrush, QColor, QFont, QPen

# ====== デバッグ用：テストMIDI固定パス ======
TEST_MIDI_PATH = r"C:\Users\tubasa usami\pythoncode\pomodoro\music\45秒で何ができる.mid"

# ====== 表示系の定数 ======
SCENE_W, SCENE_H = 700, 600
LANES = 4
LANE_W = SCENE_W / LANES
JUDGE_Y = 500  # 判定ラインY
NOTE_W, NOTE_H = 100, 20
NOTE_SPEED = 300.0  # px/sec
JUST_PX = 10
GOOD_PX = 30
# 追加: 判定ライン到達までの移動時間（秒）
AUDIO_DELAY = max((JUDGE_Y - NOTE_H/2) / NOTE_SPEED, 0.0)


class NoteItem(QGraphicsRectItem):
    def __init__(self, start_time, column, width, height):
        super().__init__(-width/2, -height/2, width, height)
        self.start_time = start_time  # 秒
        self.column = column          # 0..3
        self.hit = False

class MidiGame(QWidget):
    """
    Pygame版でのロジック（ノーツ生成/描画/判定）をPyQtへ移植。
    - generate_notes(): 時間バケツで間引き
    - _update_game(): 位置更新＆Miss処理
    - keyPressEvent(): Just/Good/Miss 判定
    """
    def __init__(self, midi_path, preview_mode=False, difficulty="Easy"):
        super().__init__()
        self.setWindowTitle("PyQt MIDI Game")
        self.setFixedSize(SCENE_W, SCENE_H)

        self.preview_mode = preview_mode
        self.difficulty = difficulty  # "Easy" | "Normal" | "Hard"
        self.font = QFont("Arial", 14)

        # Scene / View
        self.scene = QGraphicsScene(0, 0, SCENE_W, SCENE_H)
        self.view = QGraphicsView(self.scene, self)
        self.view.setGeometry(0, 0, SCENE_W, SCENE_H)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setFocusPolicy(Qt.NoFocus)
        self.setFocusPolicy(Qt.StrongFocus)

        # 判定ライン
        pen = QPen(QColor(0, 0, 0))
        pen.setWidth(2)
        self.scene.addLine(0, JUDGE_Y, SCENE_W, JUDGE_Y, pen)
        # レーン区切り
        grid_pen = QPen(QColor(80, 80, 80))
        for i in range(LANES + 1):
            x = i * LANE_W
            self.scene.addLine(x, 0, x, SCENE_H, grid_pen)

        # スコア表示
        self.combo = 0
        self.just = 0
        self.good = 0
        self.miss = 0
        self.text_combo = self.scene.addText("Combo: 0", self.font)
        self.text_combo.setDefaultTextColor(QColor(255,255,255))
        self.text_combo.setPos(10, 10)
        self.text_just = self.scene.addText("Just: 0", self.font)
        self.text_just.setDefaultTextColor(QColor(0,255,0))
        self.text_just.setPos(10, 30)
        self.text_good = self.scene.addText("Good: 0", self.font)
        self.text_good.setDefaultTextColor(QColor(255,255,0))
        self.text_good.setPos(10, 50)
        self.text_miss = self.scene.addText("Miss: 0", self.font)
        self.text_miss.setDefaultTextColor(QColor(255,0,0))
        self.text_miss.setPos(10, 70)

        # 判定テキスト（短時間表示）
        self.floating_texts = []  # [(QGraphicsTextItem, expire_epoch), ...]

        # MIDI 読み込み（描画用と送出用を分ける）
        self.midi_for_gen = mido.MidiFile(midi_path)
        self.midi_for_play = mido.MidiFile(midi_path)

        # ノーツ作成
        self.notes = []  # [NoteItem ...]
        self._prepare_notes()

        # MIDI 出力（音）
        self.midi_out = None
        try:
            pygame.midi.init()
            default_id = pygame.midi.get_default_output_id()
            self.midi_out = pygame.midi.Output(default_id) if default_id != -1 else None
        except Exception:
            self.midi_out = None

        # 再生スレッド開始
        self.start_time = time.time()
        self.midi_thread = threading.Thread(target=self._play_midi_thread, daemon=True)
        self.midi_thread.start()

        # プレビュー時は透過＆クリック透過
        if preview_mode:
            flags = Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.WindowTransparentForInput
            self.setWindowFlags(flags)
            self.setWindowOpacity(0.5)
        else:
            self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)

        # ゲームループ
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_game)
        self.timer.start(16)

        self.show()

    # ====== ノーツ生成（Pygame版の時間バケツ方式を移植） ======
    def _prepare_notes(self):
        bucket = {"Easy": 0.3, "Normal": 0.15, "Hard": 0.1}.get(self.difficulty, 0.15)
        # midoのplay()は秒ベースのデルタを出してくれるので、それを累積して絶対秒にする
        times = []
        t = 0.0
        
        for msg in self.midi_for_gen:
            t += msg.time
            if msg.type == "note_on" and getattr(msg, "velocity", 0) > 0:
                times.append(t)

        # 時間バケツにまとめ、各バケツから1ノーツずつ抽出
        buckets = defaultdict(list)
        for tt in times:
            key = round(tt / bucket) * bucket
            buckets[key].append(tt)

        filtered_times = []
        for key, arr in sorted(buckets.items()):
            filtered_times.append(random.choice(arr))

        # レーン割り当て（直近2つと同じレーンは避ける）
        last = []
        for tt in filtered_times:
            candidates = list(range(LANES))
            if len(last) >= 2 and last[-1] == last[-2]:
                # 直近2回と違うレーンを選ぶ
                candidates = [c for c in candidates if c != last[-1]]
            col = random.choice(candidates)
            last.append(col)

            lane_x = col * LANE_W + LANE_W / 2
            note = NoteItem(tt, col, NOTE_W, NOTE_H)
            note.setBrush(QBrush(QColor(0, 204, 255)))
            note.setPos(lane_x, -50)  # 初期は上部に置いておく
            self.scene.addItem(note)
            self.notes.append(note)

    # ====== MIDI送出（mido→pygame.midi） ======
    def _play_midi_thread(self):
        time.sleep(AUDIO_DELAY)
        start = time.time()
        # mido.MidiFile.play() は時刻調整済みで順にyieldされる
        for msg in self.midi_for_play.play(meta_messages=True):
            if msg.type in ("note_on", "note_off") and self.midi_out:
                status = 0x90 if msg.type == "note_on" else 0x80
                note = getattr(msg, "note", 0)
                vel = getattr(msg, "velocity", 0)
                try:
                    self.midi_out.write_short(status, note, vel)
                except Exception:
                    pass
            # msg.time は「次のメッセージまでの秒」だが、play()がsleep調整するのでここは不要
            # （別スレッドなのでここでsleepしない）

    # ====== ゲーム更新・ミス判定 ======
    def _update_game(self):
        now = time.time() - self.start_time
        # ノーツ位置更新
        for note in self.notes:
            if note.hit:
                continue
            y = (now - note.start_time) * NOTE_SPEED
            note.setY(y)
            # 画面下に抜けたらMISS
            if y - NOTE_H/2 > SCENE_H:
                note.hit = True
                note.setVisible(False)
                self.miss += 1
                self.combo = 0
                self._spawn_floating_text("Miss", note.column, QColor(255, 0, 0))

        # フローティングテキストの寿命管理
        self._gc_floating_texts()

        # スコア表示更新
        self.text_combo.setPlainText(f"Combo: {self.combo}")
        self.text_just.setPlainText(f"Just: {self.just}")
        self.text_good.setPlainText(f"Good: {self.good}")
        self.text_miss.setPlainText(f"Miss: {self.miss}")

    # ====== キー入力→判定 ======
    def keyPressEvent(self, e):
        if self.preview_mode:
            return
        keymap = {Qt.Key_D:0, Qt.Key_F:1, Qt.Key_J:2, Qt.Key_K:3}
        if e.key() not in keymap:
            super().keyPressEvent(e)
            return

        col = keymap[e.key()]
        # 最も判定ラインに近いアクティブノーツを探す
        target = None
        best_delta = 1e9
        for note in self.notes:
            if note.hit or note.column != col:
                continue
            center_y = note.y() + NOTE_H/2
            delta = abs(center_y - JUDGE_Y)
            if delta < best_delta:
                best_delta = delta
                target = note

        if not target:
            # 可視ノーツがない → ミス
            self.miss += 1
            self.combo = 0
            self._spawn_floating_text("Miss", col, QColor(255, 0, 0))
            return

        if best_delta <= JUST_PX:
            target.hit = True
            target.setVisible(False)
            self.just += 1
            self.combo += 1
            self._spawn_floating_text("Just", col, QColor(0, 255, 0))
        elif best_delta <= GOOD_PX:
            target.hit = True
            target.setVisible(False)
            self.good += 1
            self.combo += 1
            self._spawn_floating_text("Good", col, QColor(255, 255, 0))
        else:
            # 判定圏外
            self.miss += 1
            self.combo = 0
            self._spawn_floating_text("Miss", col, QColor(255, 0, 0))

    # ====== 判定テキスト ======
    def _spawn_floating_text(self, text, col, color):
        x = col * LANE_W + LANE_W / 2
        titem = self.scene.addText(text, self.font)
        titem.setDefaultTextColor(color)
        titem.setPos(x - 20, JUDGE_Y - 50)
        expire = time.time() + 0.25
        self.floating_texts.append((titem, expire))

    def _gc_floating_texts(self):
        now = time.time()
        alive = []
        for item, exp in self.floating_texts:
            if now > exp:
                self.scene.removeItem(item)
                continue
            alive.append((item, exp))
        self.floating_texts = alive

    # ====== プレビュー解除（フォーカス確保含む） ======
    def enable_interaction(self):
        self.preview_mode = False
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        self.setWindowOpacity(1.0)
        self.show()
        self._focus_game_window()

    def _focus_game_window(self):
        self.view.clearFocus()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.ActiveWindowFocusReason)
        QTimer.singleShot(0,   lambda: (self.raise_(), self.activateWindow(), self.setFocus(Qt.ActiveWindowFocusReason)))
        QTimer.singleShot(120, lambda: (self.raise_(), self.activateWindow(), self.setFocus(Qt.ActiveWindowFocusReason)))

    # ====== 終了処理（pygame.midiのガード含む） ======
    def closeEvent(self, e):
        try:
            self.timer.stop()
        except Exception:
            pass
        try:
            if self.midi_out:
                self.midi_out.close()
        except Exception:
            pass
        try:
            if pygame.midi.get_init():
                pygame.midi.quit()
        except Exception:
            pass
        super().closeEvent(e)


# =========================
# スタンドアロン実行（デバッグ）
# =========================
def _debug_generate_midi(path="generated_test.mid"):
    """簡易テストMIDIを生成（存在しないときの保険）。"""
    mid = mido.MidiFile()
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage('set_tempo', tempo=500000, time=0))  # 120 BPM相当
    # 4小節ぶんぐらい適当に
    for i in range(32):
        track.append(mido.Message('note_on', note=60 + (i % 8), velocity=90, time=120))
        track.append(mido.Message('note_off', note=60 + (i % 8), velocity=64, time=120))
    mid.save(path)
    return path

def debug_run(midi_path=None, preview=False, choose=False, use_test_default=True, difficulty="Normal"):
    """
    単体デバッグ起動：
      優先順位 1) midi_path 2) choose 3) TEST_MIDI_PATH 4) 自動生成
    """
    app = QApplication.instance() or QApplication(sys.argv)

    path = midi_path
    if choose and not path:
        dlg = QFileDialog(None, "MIDIファイルを選択")
        dlg.setNameFilter("MIDI Files (*.mid *.midi)")
        if dlg.exec_():
            files = dlg.selectedFiles()
            if files:
                path = files[0]

    if not path and use_test_default:
        path = TEST_MIDI_PATH

    if not path or not os.path.isfile(path):
        print(f"[INFO] Using generated test MIDI (not found: {path!r})")
        path = _debug_generate_midi()

    game = MidiGame(path, preview_mode=preview, difficulty=difficulty)
    return app.exec_()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="PyQt MIDI Game (standalone debug)")
    parser.add_argument("midi", nargs="?", help="Path to MIDI file.")
    parser.add_argument("--preview", action="store_true", help="Start in preview (semi-transparent).")
    parser.add_argument("--choose", action="store_true", help="Open file chooser.")
    parser.add_argument("--no-test", action="store_true", help="Do NOT use TEST_MIDI_PATH by default.")
    parser.add_argument("--difficulty", choices=["Easy","Normal","Hard"], default="Normal")
    args = parser.parse_args()

    sys.exit(debug_run(
        midi_path=args.midi,
        preview=args.preview,
        choose=args.choose,
        use_test_default=not args.no_test,
        difficulty=args.difficulty
    ))
