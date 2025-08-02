"""
Tetris for PicoCalc
A complete implementation of the classic Tetris game in MicroPython
Features:
- All 7 tetromino pieces (I, O, T, S, Z, J, L)
- Rotation and collision detection
- Line clearing and scoring
- Progressive speed increase
- Next piece preview
- Game over detection
"""

import picocalc
import utime
import urandom
import gc
from machine import Pin, PWM

# Arrow key escape sequences for PicoCalc
KEY_UP = b'\x1b[A'      # Up arrow (rotate)
KEY_DOWN = b'\x1b[B'    # Down arrow (soft drop)
KEY_LEFT = b'\x1b[D'    # Left arrow (move left)
KEY_RIGHT = b'\x1b[C'   # Right arrow (move right)
KEY_ESC = b'\x1b\x1b'   # Escape key (pause/exit)

# Audio pins for PicoCalc
AUDIO_LEFT = 28  # PWM_L
AUDIO_RIGHT = 27  # PWM_R

# Game constants
BOARD_WIDTH = 10
BOARD_HEIGHT = 20
BLOCK_SIZE = 12  # Increased from 8 to 12 pixels
BOARD_X = 20     # Moved left from 50 to 20
BOARD_Y = 30     # Moved down slightly from 20 to 30

# Color definitions (4-bit grayscale for PicoCalc display)
COLOR_BLACK = 0
COLOR_DARK_GRAY = 5
COLOR_GRAY = 8
COLOR_LIGHT_GRAY = 11
COLOR_WHITE = 15

# Theme colors
COLOR_BACKGROUND = COLOR_BLACK
COLOR_BORDER = COLOR_LIGHT_GRAY
COLOR_TEXT = COLOR_WHITE
COLOR_TEXT_DIM = COLOR_GRAY
COLOR_GHOST = COLOR_DARK_GRAY
COLOR_HIGHLIGHT = COLOR_WHITE
COLOR_TITLE = COLOR_WHITE

# Piece colors (different shades for different pieces)
PIECE_COLORS = {
    'I': COLOR_WHITE,      # Brightest
    'O': COLOR_LIGHT_GRAY, # Yellow-ish
    'T': 13,               # Purple-ish
    'S': 10,               # Green-ish
    'Z': 9,                # Red-ish
    'J': 7,                # Blue-ish
    'L': 12                # Orange-ish
}

# Tetromino definitions (4x4 grids, multiple rotations)
TETROMINOES = {
    'I': [
        [[0,0,0,0],[1,1,1,1],[0,0,0,0],[0,0,0,0]], # Horizontal
        [[0,0,1,0],[0,0,1,0],[0,0,1,0],[0,0,1,0]], # Vertical
        [[0,0,0,0],[0,0,0,0],[1,1,1,1],[0,0,0,0]], # Horizontal
        [[0,1,0,0],[0,1,0,0],[0,1,0,0],[0,1,0,0]]  # Vertical
    ],
    'O': [
        [[0,0,0,0],[0,1,1,0],[0,1,1,0],[0,0,0,0]], # Square (no rotation needed)
        [[0,0,0,0],[0,1,1,0],[0,1,1,0],[0,0,0,0]],
        [[0,0,0,0],[0,1,1,0],[0,1,1,0],[0,0,0,0]],
        [[0,0,0,0],[0,1,1,0],[0,1,1,0],[0,0,0,0]]
    ],
    'T': [
        [[0,0,0,0],[0,1,0,0],[1,1,1,0],[0,0,0,0]], # T-shape up
        [[0,0,0,0],[0,1,0,0],[0,1,1,0],[0,1,0,0]], # T-shape right
        [[0,0,0,0],[0,0,0,0],[1,1,1,0],[0,1,0,0]], # T-shape down
        [[0,0,0,0],[0,1,0,0],[1,1,0,0],[0,1,0,0]]  # T-shape left
    ],
    'S': [
        [[0,0,0,0],[0,1,1,0],[1,1,0,0],[0,0,0,0]], # S-shape horizontal
        [[0,0,0,0],[0,1,0,0],[0,1,1,0],[0,0,1,0]], # S-shape vertical
        [[0,0,0,0],[0,0,0,0],[0,1,1,0],[1,1,0,0]], # S-shape horizontal
        [[0,0,0,0],[1,0,0,0],[1,1,0,0],[0,1,0,0]]  # S-shape vertical
    ],
    'Z': [
        [[0,0,0,0],[1,1,0,0],[0,1,1,0],[0,0,0,0]], # Z-shape horizontal
        [[0,0,0,0],[0,0,1,0],[0,1,1,0],[0,1,0,0]], # Z-shape vertical
        [[0,0,0,0],[0,0,0,0],[1,1,0,0],[0,1,1,0]], # Z-shape horizontal
        [[0,0,0,0],[0,1,0,0],[1,1,0,0],[1,0,0,0]]  # Z-shape vertical
    ],
    'J': [
        [[0,0,0,0],[1,0,0,0],[1,1,1,0],[0,0,0,0]], # J-shape
        [[0,0,0,0],[0,1,1,0],[0,1,0,0],[0,1,0,0]], # J-shape rotated
        [[0,0,0,0],[0,0,0,0],[1,1,1,0],[0,0,1,0]], # J-shape
        [[0,0,0,0],[0,1,0,0],[0,1,0,0],[1,1,0,0]]  # J-shape rotated
    ],
    'L': [
        [[0,0,0,0],[0,0,1,0],[1,1,1,0],[0,0,0,0]], # L-shape
        [[0,0,0,0],[0,1,0,0],[0,1,0,0],[0,1,1,0]], # L-shape rotated
        [[0,0,0,0],[0,0,0,0],[1,1,1,0],[1,0,0,0]], # L-shape
        [[0,0,0,0],[1,1,0,0],[0,1,0,0],[0,1,0,0]]  # L-shape rotated
    ]
}

class TetrisSound:
    """Simple sound effects for Tetris"""
    def __init__(self):
        # Initialize PWM for audio
        self.audio_left = PWM(Pin(AUDIO_LEFT))
        self.audio_right = PWM(Pin(AUDIO_RIGHT))
        self.sound_enabled = True
        self.volume = 0.3  # Keep volume low for game sounds
    
    def play_tone(self, frequency, duration_ms, volume=None):
        """Play a single tone"""
        if not self.sound_enabled:
            return
        
        vol = volume if volume else self.volume
        duty = int(32768 * vol)  # 50% duty cycle scaled by volume
        
        # Set frequency and duty cycle
        self.audio_left.freq(frequency)
        self.audio_right.freq(frequency)
        self.audio_left.duty_u16(duty)
        self.audio_right.duty_u16(duty)
        
        # Play for duration
        utime.sleep_ms(duration_ms)
        
        # Stop sound
        self.audio_left.duty_u16(0)
        self.audio_right.duty_u16(0)
    
    def play_sequence(self, notes):
        """Play a sequence of notes [(freq, duration), ...]"""
        if not self.sound_enabled:
            return
        
        for freq, duration in notes:
            if freq > 0:  # 0 frequency means silence
                self.play_tone(freq, duration)
            else:
                utime.sleep_ms(duration)
    
    def sound_move(self):
        """Sound for piece movement"""
        self.play_tone(200, 20, 0.2)
    
    def sound_rotate(self):
        """Sound for piece rotation"""
        self.play_tone(400, 30, 0.25)
    
    def sound_drop(self):
        """Sound for piece drop/lock"""
        self.play_sequence([(300, 20), (250, 30)])
    
    def sound_line_clear(self, lines_count):
        """Sound for clearing lines (higher pitch for more lines)"""
        base_freq = 500
        notes = []
        for i in range(lines_count):
            freq = base_freq + (i * 200)
            notes.append((freq, 50))
            notes.append((0, 10))  # Small gap
        self.play_sequence(notes)
    
    def sound_tetris(self):
        """Special sound for clearing 4 lines (Tetris)"""
        notes = [
            (523, 50), (659, 50), (784, 50), (1047, 100),
            (0, 50),
            (1047, 50), (784, 50), (659, 50), (523, 100)
        ]
        self.play_sequence(notes)
    
    def sound_game_over(self):
        """Sound for game over"""
        notes = [
            (440, 100), (415, 100), (392, 100), (370, 100),
            (349, 100), (330, 100), (311, 200)
        ]
        self.play_sequence(notes)
    
    def sound_level_up(self):
        """Sound for level increase"""
        notes = [
            (523, 50), (587, 50), (659, 50), (698, 50),
            (784, 100)
        ]
        self.play_sequence(notes)
    
    def toggle_sound(self):
        """Toggle sound on/off"""
        self.sound_enabled = not self.sound_enabled
        if self.sound_enabled:
            self.play_tone(440, 100)  # Confirmation beep
        return self.sound_enabled

class TetrisGame:
    def __init__(self):
        self.display = picocalc.display
        self.width, self.height = self.display.width, self.display.height
        
        # Initialize sound system
        self.sound = TetrisSound()
        
        # Game state
        self.board = [[0 for _ in range(BOARD_WIDTH)] for _ in range(BOARD_HEIGHT)]
        self.board_colors = [[COLOR_BLACK for _ in range(BOARD_WIDTH)] for _ in range(BOARD_HEIGHT)]
        self.score = 0
        self.lines_cleared = 0
        self.level = 1
        self.game_over = False
        self.paused = False
        
        # Current piece
        self.current_piece = None
        self.current_type = None
        self.current_rotation = 0
        self.current_x = 0
        self.current_y = 0
        
        # Next piece
        self.next_piece = None
        self.next_type = None
        
        # Timing
        self.last_fall = utime.ticks_ms()
        self.fall_speed = 1000  # milliseconds
        
        # Input
        self.key_buffer = bytearray(10)
        
        # Initialize first pieces
        self.spawn_new_piece()
        self.generate_next_piece()
        
        print("Tetris initialized!")
        print("Sound enabled (press S to toggle)")
        
    def generate_next_piece(self):
        """Generate the next piece"""
        pieces = list(TETROMINOES.keys())
        self.next_type = pieces[urandom.randint(0, len(pieces) - 1)]
        self.next_piece = TETROMINOES[self.next_type][0]
    
    def spawn_new_piece(self):
        """Spawn a new piece at the top"""
        if self.next_piece:
            self.current_type = self.next_type
            self.current_piece = self.next_piece
            self.current_rotation = 0
        else:
            pieces = list(TETROMINOES.keys())
            self.current_type = pieces[urandom.randint(0, len(pieces) - 1)]
            self.current_piece = TETROMINOES[self.current_type][0]
            self.current_rotation = 0
        
        # Start position
        self.current_x = BOARD_WIDTH // 2 - 2
        self.current_y = 0
        
        # Check for game over
        if self.check_collision(self.current_x, self.current_y, self.current_piece):
            self.game_over = True
            self.sound.sound_game_over()
            return
        
        # Generate next piece
        self.generate_next_piece()
    
    def check_collision(self, x, y, piece):
        """Check if piece collides with board or boundaries"""
        for py in range(4):
            for px in range(4):
                if piece[py][px]:
                    new_x = x + px
                    new_y = y + py
                    
                    # Check boundaries
                    if new_x < 0 or new_x >= BOARD_WIDTH or new_y >= BOARD_HEIGHT:
                        return True
                    
                    # Check board collision (ignore negative y for spawning)
                    if new_y >= 0 and self.board[new_y][new_x]:
                        return True
        return False
    
    def place_piece(self):
        """Place current piece on the board"""
        for py in range(4):
            for px in range(4):
                if self.current_piece[py][px]:
                    board_x = self.current_x + px
                    board_y = self.current_y + py
                    if 0 <= board_x < BOARD_WIDTH and 0 <= board_y < BOARD_HEIGHT:
                        self.board[board_y][board_x] = 1
                        self.board_colors[board_y][board_x] = PIECE_COLORS.get(self.current_type, COLOR_WHITE)
        
        # Check for completed lines
        self.clear_lines()
        
        # Play drop sound
        self.sound.sound_drop()
        
        # Spawn new piece
        self.spawn_new_piece()
    
    def clear_lines(self):
        """Clear completed lines and update score"""
        lines_to_clear = []
        
        # Find completed lines
        for y in range(BOARD_HEIGHT):
            if all(self.board[y]):
                lines_to_clear.append(y)
        
        # Remove completed lines
        for y in lines_to_clear:
            del self.board[y]
            del self.board_colors[y]
            self.board.insert(0, [0 for _ in range(BOARD_WIDTH)])
            self.board_colors.insert(0, [COLOR_BLACK for _ in range(BOARD_WIDTH)])
        
        # Update score and level
        lines_count = len(lines_to_clear)
        if lines_count > 0:
            self.lines_cleared += lines_count
            
            # Scoring system
            line_scores = {1: 100, 2: 300, 3: 500, 4: 800}
            self.score += line_scores.get(lines_count, 0) * self.level
            
            # Play sound effects
            if lines_count == 4:
                self.sound.sound_tetris()  # Special Tetris sound
            else:
                self.sound.sound_line_clear(lines_count)
            
            # Level progression
            old_level = self.level
            self.level = (self.lines_cleared // 10) + 1
            if self.level > old_level:
                self.sound.sound_level_up()
            self.fall_speed = max(100, 1000 - (self.level - 1) * 80)
    
    def rotate_piece(self):
        """Rotate current piece"""
        new_rotation = (self.current_rotation + 1) % 4
        new_piece = TETROMINOES[self.current_type][new_rotation]
        
        if not self.check_collision(self.current_x, self.current_y, new_piece):
            self.current_rotation = new_rotation
            self.current_piece = new_piece
            self.sound.sound_rotate()
            return True
        
        # Try wall kicks (simple implementation)
        for kick_x in [-1, 1, -2, 2]:
            if not self.check_collision(self.current_x + kick_x, self.current_y, new_piece):
                self.current_rotation = new_rotation
                self.current_piece = new_piece
                self.current_x += kick_x
                self.sound.sound_rotate()
                return True
        
        return False
    
    def move_piece(self, dx, dy):
        """Move current piece"""
        new_x = self.current_x + dx
        new_y = self.current_y + dy
        
        if not self.check_collision(new_x, new_y, self.current_piece):
            self.current_x = new_x
            self.current_y = new_y
            # Only play move sound for horizontal movement
            if dx != 0:
                self.sound.sound_move()
            return True
        return False
    
    def hard_drop(self):
        """Drop piece to bottom instantly"""
        while self.move_piece(0, 1):
            self.score += 2  # Bonus points for hard drop
        self.place_piece()
    
    def soft_drop(self):
        """Move piece down one row"""
        if self.move_piece(0, 1):
            self.score += 1  # Bonus point for soft drop
            return True
        return False
    
    def update_game(self):
        """Update game logic"""
        if self.game_over or self.paused:
            return
        
        current_time = utime.ticks_ms()
        
        # Natural falling
        if utime.ticks_diff(current_time, self.last_fall) >= self.fall_speed:
            if not self.move_piece(0, 1):
                self.place_piece()
            self.last_fall = current_time
    
    def draw_block(self, x, y, filled=True, color=COLOR_WHITE):
        """Draw a single block with specified color"""
        if filled:
            self.display.fill_rect(x, y, BLOCK_SIZE - 1, BLOCK_SIZE - 1, color)
        else:
            self.display.rect(x, y, BLOCK_SIZE - 1, BLOCK_SIZE - 1, color)
    
    def draw_board(self):
        """Draw the game board"""
        # Board border
        border_x = BOARD_X - 1
        border_y = BOARD_Y - 1
        border_w = BOARD_WIDTH * BLOCK_SIZE + 1
        border_h = BOARD_HEIGHT * BLOCK_SIZE + 1
        
        self.display.rect(border_x, border_y, border_w, border_h, COLOR_BORDER)
        
        # Draw placed blocks
        for y in range(BOARD_HEIGHT):
            for x in range(BOARD_WIDTH):
                if self.board[y][x]:
                    block_x = BOARD_X + x * BLOCK_SIZE
                    block_y = BOARD_Y + y * BLOCK_SIZE
                    color = self.board_colors[y][x]
                    self.draw_block(block_x, block_y, True, color)
    
    def draw_current_piece(self):
        """Draw the currently falling piece"""
        if not self.current_piece:
            return
        
        for py in range(4):
            for px in range(4):
                if self.current_piece[py][px]:
                    block_x = BOARD_X + (self.current_x + px) * BLOCK_SIZE
                    block_y = BOARD_Y + (self.current_y + py) * BLOCK_SIZE
                    
                    # Only draw if within visible board area
                    if block_y >= BOARD_Y:
                        color = PIECE_COLORS.get(self.current_type, COLOR_WHITE)
                        self.draw_block(block_x, block_y, True, color)
    
    def draw_ghost_piece(self):
        """Draw ghost piece showing where current piece will land"""
        if not self.current_piece:
            return
        
        # Find ghost position
        ghost_y = self.current_y
        while not self.check_collision(self.current_x, ghost_y + 1, self.current_piece):
            ghost_y += 1
        
        # Draw ghost piece (outline only)
        if ghost_y != self.current_y:
            for py in range(4):
                for px in range(4):
                    if self.current_piece[py][px]:
                        block_x = BOARD_X + (self.current_x + px) * BLOCK_SIZE
                        block_y = BOARD_Y + (ghost_y + py) * BLOCK_SIZE
                        
                        if block_y >= BOARD_Y:
                            self.draw_block(block_x, block_y, False, COLOR_GHOST)
    
    def draw_next_piece(self):
        """Draw the next piece preview"""
        if not self.next_piece:
            return
        
        # Next piece area - positioned to the right of the larger board
        next_x = BOARD_X + BOARD_WIDTH * BLOCK_SIZE + 15  # Adjusted for larger board
        next_y = BOARD_Y + 20
        
        self.display.text("NEXT:", next_x, next_y - 15, COLOR_TEXT)
        self.display.rect(next_x - 2, next_y - 2, 4 * BLOCK_SIZE + 3, 4 * BLOCK_SIZE + 3, COLOR_BORDER)
        
        # Draw next piece
        for py in range(4):
            for px in range(4):
                if self.next_piece[py][px]:
                    block_x = next_x + px * BLOCK_SIZE
                    block_y = next_y + py * BLOCK_SIZE
                    color = PIECE_COLORS.get(self.next_type, COLOR_WHITE)
                    self.draw_block(block_x, block_y, True, color)
    
    def draw_stats(self):
        """Draw game statistics"""
        stats_x = BOARD_X + BOARD_WIDTH * BLOCK_SIZE + 15  # Adjusted for larger board
        stats_y = BOARD_Y + 120  # Moved down to accommodate larger next piece
        
        self.display.text(f"SCORE:", stats_x, stats_y, COLOR_TEXT)
        self.display.text(f"{self.score}", stats_x, stats_y + 12, COLOR_HIGHLIGHT)
        
        self.display.text(f"LINES:", stats_x, stats_y + 30, COLOR_TEXT)
        self.display.text(f"{self.lines_cleared}", stats_x, stats_y + 42, COLOR_HIGHLIGHT)
        
        self.display.text(f"LEVEL:", stats_x, stats_y + 60, COLOR_TEXT)
        self.display.text(f"{self.level}", stats_x, stats_y + 72, COLOR_HIGHLIGHT)
    
    def draw_controls(self):
        """Draw control instructions"""
        controls_y = self.height - 40  # Moved up from bottom to avoid overlap
        
        # Compact controls display for bottom of screen
        self.display.text("↑:Rot ←→:Move ↓:Drop", 10, controls_y, COLOR_TEXT_DIM)
        self.display.text("SPACE:Hard P:Pause", 10, controls_y + 12, COLOR_TEXT_DIM)
        self.display.text("S:Sound ESC:Exit", 10, controls_y + 24, COLOR_TEXT_DIM)
    
    def draw_game_over(self):
        """Draw game over screen"""
        # Game over box
        box_x = self.width // 2 - 60
        box_y = self.height // 2 - 40
        box_w = 120
        box_h = 80
        
        self.display.fill_rect(box_x, box_y, box_w, box_h, COLOR_BLACK)
        self.display.rect(box_x, box_y, box_w, box_h, COLOR_HIGHLIGHT)
        self.display.rect(box_x + 1, box_y + 1, box_w - 2, box_h - 2, COLOR_BORDER)
        
        # Game over text
        self.display.text("GAME OVER", box_x + 15, box_y + 15, COLOR_HIGHLIGHT)
        self.display.text(f"Score: {self.score}", box_x + 20, box_y + 35, COLOR_TEXT)
        self.display.text(f"Lines: {self.lines_cleared}", box_x + 20, box_y + 47, COLOR_TEXT)
        self.display.text("R: Restart", box_x + 20, box_y + 59, COLOR_HIGHLIGHT)
    
    def draw_pause(self):
        """Draw pause screen"""
        pause_x = self.width // 2 - 30
        pause_y = self.height // 2 - 10
        
        self.display.fill_rect(pause_x - 5, pause_y - 5, 70, 30, COLOR_BLACK)
        self.display.rect(pause_x - 5, pause_y - 5, 70, 30, COLOR_BORDER)
        self.display.text("PAUSED", pause_x, pause_y, COLOR_HIGHLIGHT)
        self.display.text("P: Resume", pause_x - 3, pause_y + 12, COLOR_TEXT)
    
    def draw(self):
        """Draw the entire game"""
        self.display.fill(0)
        
        # Title - centered at top
        title_text = "TETRIS"
        if not self.sound.sound_enabled:
            title_text += " [MUTE]"
        self.display.text(title_text, 10, 10, COLOR_TITLE)
        
        # Game elements
        self.draw_board()
        
        if not self.game_over:
            self.draw_ghost_piece()
            self.draw_current_piece()
        
        self.draw_next_piece()
        self.draw_stats()
        self.draw_controls()
        
        # Overlays
        if self.game_over:
            self.draw_game_over()
        elif self.paused:
            self.draw_pause()
        
        self.display.show()
    
    def handle_input(self):
        """Handle keyboard input"""
        if not picocalc.terminal:
            return False
        
        count = picocalc.terminal.readinto(self.key_buffer)
        if not count:
            return False
        
        key_data = bytes(self.key_buffer[:count])
        
        # ESC key - exit game
        if key_data == KEY_ESC:
            return "EXIT"
        
        # Game over state
        if self.game_over:
            if count == 1 and (self.key_buffer[0] == ord('r') or self.key_buffer[0] == ord('R')):
                self.restart_game()
            return True
        
        # Sound toggle (works in any state)
        if count == 1 and (self.key_buffer[0] == ord('s') or self.key_buffer[0] == ord('S')):
            enabled = self.sound.toggle_sound()
            print(f"Sound {'enabled' if enabled else 'disabled'}")
            self.update_display()
            return True
        
        # Pause state
        if count == 1 and (self.key_buffer[0] == ord('p') or self.key_buffer[0] == ord('P')):
            self.paused = not self.paused
            return True
        
        if self.paused:
            return True
        
        # Game controls
        if key_data == KEY_UP:  # Rotate
            self.rotate_piece()
        elif key_data == KEY_LEFT:  # Move left
            self.move_piece(-1, 0)
        elif key_data == KEY_RIGHT:  # Move right
            self.move_piece(1, 0)
        elif key_data == KEY_DOWN:  # Soft drop
            self.soft_drop()
        elif count == 1 and self.key_buffer[0] == ord(' '):  # Hard drop
            self.hard_drop()
        
        return True
    
    def restart_game(self):
        """Restart the game"""
        self.board = [[0 for _ in range(BOARD_WIDTH)] for _ in range(BOARD_HEIGHT)]
        self.board_colors = [[COLOR_BLACK for _ in range(BOARD_WIDTH)] for _ in range(BOARD_HEIGHT)]
        self.score = 0
        self.lines_cleared = 0
        self.level = 1
        self.game_over = False
        self.paused = False
        self.fall_speed = 1000
        self.last_fall = utime.ticks_ms()
        
        self.spawn_new_piece()
        self.generate_next_piece()
        
        print("Game restarted!")
    
    def run(self):
        """Main game loop"""
        print("Starting Tetris...")
        print("Use arrow keys to play, P to pause, ESC to exit")
        
        try:
            while True:
                # Handle input
                result = self.handle_input()
                if result == "EXIT":
                    break
                
                # Update game logic
                self.update_game()
                
                # Draw everything
                self.draw()
                
                # Small delay for smoother gameplay
                utime.sleep_ms(50)
                
        except KeyboardInterrupt:
            print("Game interrupted")
        
        # Cleanup
        self.display.fill(COLOR_BLACK)
        self.display.text("Thanks for playing Tetris!", 10, 10, COLOR_TEXT)
        self.display.show()
        utime.sleep(2)

def main():
    """Main function"""
    # Free up memory before starting
    gc.collect()
    
    try:
        print(f"Free memory: {gc.mem_free()} bytes")
        game = TetrisGame()
        game.run()
        print("Tetris exited normally")
    except Exception as e:
        print(f"Error: {e}")
        import sys
        sys.print_exception(e)

if __name__ == "__main__":
    main()