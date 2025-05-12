import sys
import time
import random
import threading
import mido
import pygame
import pygame.midi
from PyQt5.QtWidgets import (
    QApplication, QWidget, QGraphicsView, QGraphicsScene, QGraphicsRectItem, QPushButton
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QBrush, QColor, QFont, QPen, QPainter

class NoteItem(QGraphicsRectItem):
    def __init__(self, start_time, note, velocity, column):
        # ダミーで初期化。サイズは _prepare_notes で setRect() によって設定します。
        super().__init__(0, 0, 0, 0)
        self.default_brush = QBrush(QColor(0, 255, 255))
        self.setBrush(self.default_brush)
        self.start_time = start_time
        self.note = note
        self.velocity = velocity
        self.column = column
        self.hit = False

class MidiGame(QWidget):
    def __init__(self, midi_path, preview_mode=False):
        super().__init__()
        # ——— ウィンドウサイズを 700×600 に固定 ———
        self.setFixedSize(700, 600)
        self.setWindowTitle("PyQt MIDI Game")
        self.preview_mode = preview_mode

       # ——— シーン＆ビューを 700×600 に合わせる ———
        self.scene = QGraphicsScene(0, 0, 700, 600)
        self.view = QGraphicsView(self.scene, self)
        self.view.setGeometry(0, 0, 700, 600)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

       # ——— ノーツサイズを設定 ———
        # 4 列分割した幅の 80％、高さの 8％
        self.note_width  = (self.scene.width() / 4) * 0.8
        self.note_height = self.scene.height() * 0.04
        # プレビュー時は半透明・クリック透過・最前面表示
        if preview_mode:
            # 常に最前面に表示
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
            # フレームを消したい場合は以下も追加
            # self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
            # 半透明度設定（0.0～1.0）
            self.setWindowOpacity(0.5)
            # クリックを透過（マウスイベントを無視）
            self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        # Judge line: シーンの下端から100px 上に配置
        self.judge_line_y = self.scene.height() - 100
        pen = QPen(QColor(0, 0, 0))
        pen.setWidth(2)
        self.scene.addLine(
            0,
            self.judge_line_y,
            self.scene.width(),
            self.judge_line_y,
            pen
        )
        # Preview appearance: translucent & click-through
        if self.preview_mode:
            self.setWindowOpacity(0.5)
            self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            # Allow clicks to pass through window
            self.setWindowFlags(self.windowFlags() | Qt.WindowTransparentForInput)

        # Break button
        self.button = QPushButton("休憩を開始する", self)
        self.button.setGeometry(200, 660, 100, 30)
        self.button.clicked.connect(self.on_start_break)
        if not self.preview_mode:
            self.button.hide()

        # Score and judgement setup
        self.combo = 0
        self.max_combo = 0
        self.total_hits = 0
        self.just_hits = 0
        self.good_hits = 0
        self.judgements = []  # (text_item, timestamp)
        font = QFont('Arial', 14)
        self.combo_text = self.scene.addText(f"Combo: {self.combo}", font)
        self.combo_text.setDefaultTextColor(QColor(255,255,255))
        self.combo_text.setPos(10, 10)
        self.max_combo_text = self.scene.addText(f"Max Combo: {self.max_combo}", font)
        self.max_combo_text.setDefaultTextColor(QColor(255,255,255))
        self.max_combo_text.setPos(10, 30)
        self.total_hits_text = self.scene.addText(f"Total Hits: {self.total_hits}", font)
        self.total_hits_text.setDefaultTextColor(QColor(255,255,255))
        self.total_hits_text.setPos(10, 50)
        self.just_text = self.scene.addText(f"Just: {self.just_hits}", font)
        self.just_text.setDefaultTextColor(QColor(0,255,0))
        self.just_text.setPos(10, 70)
        self.good_text = self.scene.addText(f"Good: {self.good_hits}", font)
        self.good_text.setDefaultTextColor(QColor(255,255,0))
        self.good_text.setPos(10, 90)

        # Audio init
        pygame.mixer.init()
        pygame.mixer.music.load(midi_path)
        pygame.mixer.music.play()
        pygame.midi.init()
        self.midi_out = pygame.midi.Output(0)

        # MIDI data & notes
        self.midi_data = mido.MidiFile(midi_path)
        self._prepare_notes()
        threading.Thread(target=self.play_midi, daemon=True).start()

        # Timing
        self.start_time = time.time()
        self.note_speed = 300  # px/sec

        # Update timer
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_game)
        self.timer.start(16)

    def _prepare_notes(self):
        ticks = self.midi_data.ticks_per_beat
        tempo = next((msg.tempo for track in self.midi_data.tracks for msg in track if msg.type=='set_tempo'),500000)
        self.sec_per_tick = tempo/(ticks*1e6)
        raw = []
        for track in self.midi_data.tracks:
            acc = 0
            for msg in track:
                acc += msg.time
                if msg.type=='note_on' and msg.velocity>0:
                    raw.append((acc*self.sec_per_tick,msg.note))
        avg = sum(n for _,n in raw)/len(raw) if raw else 0
        filt=[(t,n) for t,n in raw if n>=avg]
        bucket=0.15; buckets={}
        for t,n in filt: buckets.setdefault(round(t/bucket)*bucket,[]).append((t,n))
        self.notes = []
        # 列幅を scene.width()/4 で計算
        col_w = self.scene.width() / 4
        for events in buckets.values():
            t, n = random.choice(events)
            col = random.randint(0, 3)
            item = NoteItem(start_time=t, note=n, velocity=64, column=col)
            # サイズを note_width/note_height に変更
            item.setRect(-self.note_width/2, -self.note_height/2,
                         self.note_width, self.note_height)
            # X 座標は各列の中央
            x = col * col_w + col_w / 2
            # Y は画面上部 (0) から落下開始
            item.setPos(x, 0)
            self.scene.addItem(item)
            self.notes.append(item)

    def play_midi(self):
        for msg in self.midi_data.play():
            if not msg.is_meta:
                data=msg.bytes()
                if len(data)>=3:
                    self.midi_out.write_short(data[0],data[1],data[2])
            time.sleep(msg.time)

    def update_game(self):
        current=time.time()-self.start_time
        # update notes
        for note in self.notes:
            if not note.hit:
                # ノーツ Y 座標を +100px シフトして曲とのズレを補正
                y = (
                    self.judge_line_y
                    - (note.start_time - current) * self.note_speed
                    - 100
                )
                note.setY(y)
        # remove old judgements
        for text_item,ts in self.judgements[:]:
            if time.time()-ts>0.5:
                self.scene.removeItem(text_item)
                self.judgements.remove((text_item,ts))
        # update score texts
        self.combo_text.setPlainText(f"Combo: {self.combo}")
        self.max_combo_text.setPlainText(f"Max Combo: {self.max_combo}")
        self.total_hits_text.setPlainText(f"Total Hits: {self.total_hits}")
        self.just_text.setPlainText(f"Just: {self.just_hits}")
        self.good_text.setPlainText(f"Good: {self.good_hits}")

    def keyPressEvent(self,event):
        if event.key()==Qt.Key_Escape or self.preview_mode: return
        mapping={Qt.Key_D:0,Qt.Key_F:1,Qt.Key_J:2,Qt.Key_K:3}
        if event.key() not in mapping: return
        col=mapping[event.key()]
        current=time.time()-self.start_time
        result="Miss"
        for note in self.notes:
            if not note.hit and note.column==col:
                diff=note.start_time-current
                if abs(diff)<0.1:
                    result="Just"
                elif abs(diff)<0.2:
                    result="Good"
                else:
                    continue
                note.hit=True;note.setBrush(QBrush(QColor(0,255,0)))
                self.midi_out.write_short(0x90,note.note,note.velocity)
                QTimer.singleShot(200,lambda n=note: self.midi_out.write_short(0x80,n.note,n.velocity))
                break
        if result=="Just":
            self.combo+=1;self.just_hits+=1;self.total_hits+=1
        elif result=="Good":
            self.combo+=1;self.good_hits+=1;self.total_hits+=1
        else:
            self.combo=0
        self.max_combo=max(self.max_combo,self.combo)
        color=QColor(0,255,0) if result=="Just" else QColor(255,255,0) if result=="Good" else QColor(255,0,0)
        text_item=self.scene.addText(result,QFont('Arial',20))
        text_item.setDefaultTextColor(color)
        x=50+col*100; text_item.setPos(x,self.judge_line_y-40)
        self.judgements.append((text_item,time.time()))

    def on_start_break(self):
        # Exit preview mode: opaque & block clicks
        self.preview_mode=False
        self.setWindowOpacity(1.0)
        self.setAttribute(Qt.WA_TransparentForMouseEvents,False)
        # Remove click-through flag
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowTransparentForInput)
        self.button.hide()

    def closeEvent(self,event):
        pygame.mixer.music.stop(); self.midi_out.close(); pygame.midi.quit()
        super().closeEvent(event)

if __name__=='__main__':
    app=QApplication(sys.argv); game=MidiGame('music/sample.mid'); game.show(); sys.exit(app.exec_())
