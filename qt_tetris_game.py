import random
import os
from PyQt5.QtWidgets import QWidget, QGraphicsScene, QGraphicsView, QGraphicsRectItem
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QBrush, QColor, QFont, QPen

# 定数
MAX_ROW = 20
MAX_COL = 10
CELL_SIZE = 35
GRID_OFFSET_X = 30
GRID_OFFSET_Y = 30
HIGH_SCORE_FILE = "tetris_highscore.txt"

class Block:
    shapes = [
        [], [],
        [[0, -1], [0, 0], [0, 1], [0, 2]],  # I
        [[-1, -1], [0, -1], [0, 0], [0, 1]],  # J
        [[0, -1], [0, 0], [0, 1], [-1, 1]],   # L
        [[0, -1], [0, 0], [-1, 0], [-1, 1]],  # S
        [[-1, -1], [-1, 0], [0, 0], [0, 1]],  # Z
        [[0, -1], [0, 0], [-1, 0], [0, 1]],   # T
        [[0, 0], [-1, 0], [0, 1], [-1, 1]],   # O
    ]

    def __init__(self, block_type):
        self.block_type = block_type
        self.shape = [coord.copy() for coord in self.shapes[block_type]]
        self.row = 1
        self.col = 5

    def _moveable(self, board, direction):
        drow, dcol = direction
        for r, c in self.shape:
            nr = self.row + r + drow
            nc = self.col + c + dcol
            if not (0 <= nc < MAX_COL and nr < MAX_ROW) or board[nr][nc] != 0:
                return False
        return True
    # qt_tetris_game.py の Block クラス内に追加

    def rotate(self, board, clockwise=True):
        """
        ブロックを90度回転させます。
        clockwise=True なら時計回り、False なら反時計回りに回転。
        壁や他のブロックとぶつかる場合は回転しません。
        """
        # O型ブロックは回転不要
        if self.block_type == 8:  
            return

        # 回転変換をかけた新しい形状を作成
        new_shape = []
        for r, c in self.shape:
            if clockwise:
                nr, nc = -c, r
            else:
                nr, nc = c, -r
            new_shape.append([nr, nc])

        # 回転後に盤面外か他ブロックと重なるかチェック
        for r, c in new_shape:
            row = self.row + r
            col = self.col + c
            if not (0 <= col < MAX_COL and 0 <= row < MAX_ROW):
                return  # 外にはみ出すので回転キャンセル
            if board[row][col] != 0:
                return  # 他のブロックと重なるので回転キャンセル

        # 問題なければ、形状を更新
        self.shape = new_shape
    def place(self, board):
        """
        ブロックの現在位置（self.row, self.col）と shape から、
        board[][] 配列にブロックを固定します。
        """
        for dr, dc in self.shape:
            r = self.row + dr
            c = self.col + dc
            # 範囲外チェック（あれば置けない）
            if not (0 <= r < MAX_ROW and 0 <= c < MAX_COL):
                continue
            board[r][c] = self.block_type  # または 1 など、好みの値


class Record:
    def __init__(self):
        self.level = 0
        self.cleared = 0
        self.score = 0
        self.score_table = [0, 80, 100, 300, 1200]

    def update(self, lines):
        self.score += self.score_table[lines] * (self.level + 1)
        self.cleared += lines
        if self.cleared > (self.level + 1) * 5 and self.level < 9:
            self.level += 1

class TetrisGame(QWidget):
    def __init__(self, preview_mode=False):
        super().__init__()
        # ハイスコア読み込み
        self.highscore = 0
        if os.path.exists(HIGH_SCORE_FILE):
            try:
                self.highscore = int(open(HIGH_SCORE_FILE).read().strip())
            except Exception:
                self.highscore = 0
        # 常に最前面＋枠なし
        base_flags = Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint
        # プレビュー時は入力透過（マウス＋キーボード）にする
        if preview_mode:
            preview_flags = base_flags | Qt.WindowTransparentForInput
            self.setWindowFlags(self.windowFlags() | preview_flags)
            # 半透明に
            self.setWindowOpacity(0.5)
        else:
            # 通常モード（枠なし＋最前面）
            self.setWindowFlags(self.windowFlags() | base_flags)
        self.setFocusPolicy(Qt.StrongFocus)

        width = GRID_OFFSET_X*2 + MAX_COL*CELL_SIZE + 300
        height = GRID_OFFSET_Y*2 + MAX_ROW*CELL_SIZE
        self.scene = QGraphicsScene(0, 0, width, height)
        self.view = QGraphicsView(self.scene, self)
        self.view.setGeometry(0, 0, width, height)
        # ── ここから追加 ──
        # 矢印キーで View がスクロールしないように
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # View がキー入力を取らない → 親ウィジェットへ
        self.view.setFocusPolicy(Qt.NoFocus)
        # このウィジェットがキー入力を受け取るように
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFocus()
        # ── ここまで追加 ─

        self._init_game()

        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self.game_loop)
        self.timer.start(500)
    
    def get_drop_interval(self):
        # レベルごとに落下速度アップ
        base = 500  # 初期500ms
        decrease = self.record.level * 40  # レベルごと40ms速く
        interval = base - decrease
        return max(100, interval)


    def _init_game(self):
        self.board = [[0]*MAX_COL for _ in range(MAX_ROW)]
        self.record = Record()
        self.current = Block(random.randint(2, 8))
        self.next_block = Block(random.randint(2, 8))

    def game_loop(self):
        if self.current._moveable(self.board, [1, 0]):
            self.current.row += 1
        else:
            self.current.place(self.board)
            lines = [row for row in self.board if 0 not in row]
            cleared = len(lines)
            self.board = [row for row in self.board if 0 in row]
            for _ in range(cleared):
                self.board.insert(0, [0]*MAX_COL)
            # レベル・スコア更新前のレベルを保持
            old_level = self.record.level
            self.record.update(cleared)
            # レベルアップがあればタイマー再設定
            if self.record.level > old_level:
                self.timer.start(self.get_drop_interval())
            self.current = self.next_block
            # ゲームオーバー判定
            for r, c in self.current.shape:
                rr = self.current.row + r
                cc = self.current.col + c
                if 0 <= rr < MAX_ROW and 0 <= cc < MAX_COL and self.board[rr][cc] != 0:
                    self.timer.stop()
                    # ハイスコア更新
                    if self.record.score > self.highscore:
                        self.highscore = self.record.score
                        with open(HIGH_SCORE_FILE, 'w') as f:
                            f.write(str(self.highscore))
                    go = self.scene.addText("GAME OVER", QFont(None, 48))
                    go.setDefaultTextColor(QColor(255, 0, 0))
                    gw = self.scene.width()
                    gh = self.scene.height()
                    go.setPos(gw/2 - 100, gh/2 - 50)
                    return
            self.next_block = Block(random.randint(2, 8))
        self.render()

    def _clear_lines(self):
        new_board = [row for row in self.board if 0 in row]
        lines = MAX_ROW - len(new_board)
        for _ in range(lines):
            new_board.insert(0, [0]*MAX_COL)
        self.board = new_board
        return lines

    def render(self):
        self.scene.clear()
        # ● ここでグリッド線を描画 ●
        pen = QPen(QColor(100, 100, 100))
        pen.setWidth(1)
        x0 = GRID_OFFSET_X
        y0 = GRID_OFFSET_Y
        w = MAX_COL * CELL_SIZE
        h = MAX_ROW * CELL_SIZE
        # 横線
        for i in range(MAX_ROW + 1):
            y = y0 + i * CELL_SIZE
            self.scene.addLine(x0, y, x0 + w, y, pen)
        # 縦線
        for j in range(MAX_COL + 1):
            x = x0 + j * CELL_SIZE
            self.scene.addLine(x, y0, x, y0 + h, pen)
        # 盤面の描画
        for r, row in enumerate(self.board):
            for c, val in enumerate(row):
                if val:
                    rect = QGraphicsRectItem(
                        x0 + c*CELL_SIZE,
                        y0 + r*CELL_SIZE,
                        CELL_SIZE, CELL_SIZE
                    )
                    rect.setBrush(QBrush(QColor(0,200,200)))
                    rect.setPen(QPen(Qt.NoPen))
                    self.scene.addItem(rect)
        # 現在ブロック描画
        brush = QBrush(QColor(200, 50, 50))
        for r, c in self.current.shape:
            rect = QGraphicsRectItem(
                GRID_OFFSET_X + (self.current.col + c)*CELL_SIZE,
                GRID_OFFSET_Y + (self.current.row + r)*CELL_SIZE,
                CELL_SIZE, CELL_SIZE
            )
            rect.setBrush(brush)
            rect.setPen(QPen(Qt.NoPen))
            self.scene.addItem(rect)
        # スコア表示
        text = self.scene.addText(f"SCORE: {self.record.score}", QFont(None, 16))
        text.setDefaultTextColor(QColor(0, 0, 0))
        text.setPos(self.scene.width() - 200, GRID_OFFSET_Y)
         # ライン数表示
        text_lines = self.scene.addText(f"LINES: {self.record.cleared}", QFont(None, 16))
        text_lines.setDefaultTextColor(QColor(0,0,0))
        text_lines.setPos(self.scene.width() - 200, GRID_OFFSET_Y + 30)
        # ハイスコア表示
        text_high = self.scene.addText(f"HIGH: {self.highscore}", QFont(None, 16))
        text_high.setDefaultTextColor(QColor(0,0,0))
        text_high.setPos(self.scene.width() - 200, y0 + 60)
        text_level = self.scene.addText(f"LEVEL: {self.record.level}", QFont(None,16))
        text_level.setDefaultTextColor(QColor(0,0,0))
        text_level.setPos(self.scene.width() - 200, y0 + 90)
        

    def keyPressEvent(self, e):
        key = e.key()
        if key == Qt.Key_Left and self.current._moveable(self.board, [0, -1]):
            self.current.col -= 1
        elif key == Qt.Key_Right and self.current._moveable(self.board, [0, 1]):
            self.current.col += 1
        elif key == Qt.Key_A:
            self.current.rotate(self.board, False)
        elif key == Qt.Key_S:
            self.current.rotate(self.board, True)
        elif key == Qt.Key_Up:
            while self.current._moveable(self.board, [1, 0]):
                self.current.row += 1
        self.render()

    def on_start_break(self):
        # プレビュー解除：不透明に戻し、入力透過フラグを外す
        self.setWindowOpacity(1.0)
        # WindowTransparentForInput を外してキーボード／マウス受け付け
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint |
            Qt.WindowTitleHint |
            Qt.WindowCloseButtonHint
        )
        self.show()  # フラグ変更を反映

    def enable_interaction(self):
        self.on_start_break()
        self.show()
