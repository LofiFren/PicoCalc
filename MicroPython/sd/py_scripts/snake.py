"""
Snake Game for PicoCalc
A classic snake game implementation in MicroPython
Features:
- Smooth snake movement
- Food collection and growth
- Score tracking
- Speed increase with score
- Game over detection
- Sound effects
"""

import picocalc
import utime
import urandom
import gc
from machine import Pin, PWM

# Arrow key escape sequences for PicoCalc
KEY_UP = b'\x1b[A'
KEY_DOWN = b'\x1b[B'
KEY_LEFT = b'\x1b[D'
KEY_RIGHT = b'\x1b[C'
KEY_ESC = b'\x1b\x1b'

# Audio pins for PicoCalc
AUDIO_LEFT = 28
AUDIO_RIGHT = 27

# Game constants
GRID_SIZE = 18  # Reduced from 20 to 18 for better fit
CELL_SIZE = 14  # Reduced from 15 to 14 pixels per cell
BOARD_X = 10
BOARD_Y = 50  # Position board below score text
INITIAL_SPEED = 200  # milliseconds between moves
MIN_SPEED = 50  # fastest speed

# Color definitions
COLOR_BLACK = 0
COLOR_DARK_GRAY = 5
COLOR_GRAY = 8
COLOR_LIGHT_GRAY = 11
COLOR_WHITE = 15

# Theme colors
COLOR_BACKGROUND = COLOR_BLACK
COLOR_BORDER = COLOR_LIGHT_GRAY
COLOR_SNAKE_HEAD = COLOR_WHITE
COLOR_SNAKE_BODY = COLOR_LIGHT_GRAY
COLOR_FOOD = 13  # Bright color for food
COLOR_TEXT = COLOR_WHITE
COLOR_TEXT_DIM = COLOR_GRAY

# Directions
DIR_UP = (0, -1)
DIR_DOWN = (0, 1)
DIR_LEFT = (-1, 0)
DIR_RIGHT = (1, 0)

class SnakeSound:
    """Simple sound effects for Snake"""
    def __init__(self):
        self.audio_left = PWM(Pin(AUDIO_LEFT))
        self.audio_right = PWM(Pin(AUDIO_RIGHT))
        self.sound_enabled = True
        self.volume = 0.3
    
    def play_tone(self, frequency, duration_ms, volume=None):
        """Play a single tone"""
        if not self.sound_enabled:
            return
        
        vol = volume if volume else self.volume
        duty = int(32768 * vol)
        
        self.audio_left.freq(frequency)
        self.audio_right.freq(frequency)
        self.audio_left.duty_u16(duty)
        self.audio_right.duty_u16(duty)
        
        utime.sleep_ms(duration_ms)
        
        self.audio_left.duty_u16(0)
        self.audio_right.duty_u16(0)
    
    def sound_eat(self):
        """Sound for eating food"""
        self.play_tone(600, 50, 0.3)
        self.play_tone(800, 50, 0.3)
    
    def sound_turn(self):
        """Sound for turning"""
        self.play_tone(200, 20, 0.2)
    
    def sound_game_over(self):
        """Sound for game over"""
        for freq in [400, 350, 300, 250]:
            self.play_tone(freq, 100)
    
    def sound_level_up(self):
        """Sound for speed increase"""
        for freq in [500, 600, 700]:
            self.play_tone(freq, 50)
    
    def toggle_sound(self):
        """Toggle sound on/off"""
        self.sound_enabled = not self.sound_enabled
        if self.sound_enabled:
            self.play_tone(440, 100)
        return self.sound_enabled

class SnakeGame:
    def __init__(self):
        self.display = picocalc.display
        self.width, self.height = self.display.width, self.display.height
        
        # Clear entire screen first to remove any menu remnants
        self.display.fill(COLOR_BLACK)
        self.display.show()
        
        # Initialize sound
        self.sound = SnakeSound()
        
        # Game state
        self.reset_game()
        
        # Input
        self.key_buffer = bytearray(10)
        
        # Track what needs redrawing
        self.needs_full_redraw = True
        self.last_score = -1
        
        print("Snake game initialized!")
        print("Sound enabled (press S to toggle)")
    
    def reset_game(self):
        """Reset game to initial state"""
        # Snake starts in center, moving right
        center_x = GRID_SIZE // 2
        center_y = GRID_SIZE // 2
        self.snake = [(center_x - 2, center_y), 
                      (center_x - 1, center_y), 
                      (center_x, center_y)]
        self.direction = DIR_RIGHT
        self.next_direction = DIR_RIGHT
        
        # Place first food
        self.food = self.generate_food()
        
        # Game state
        self.score = 0
        # Keep high score between games
        if not hasattr(self, 'high_score'):
            self.high_score = 0
        self.game_over = False
        self.paused = False
        self.speed = INITIAL_SPEED
        self.last_move = utime.ticks_ms()
        self.speed_level = 1
    
    def generate_food(self):
        """Generate food at random empty position"""
        while True:
            x = urandom.randint(0, GRID_SIZE - 1)
            y = urandom.randint(0, GRID_SIZE - 1)
            if (x, y) not in self.snake:
                return (x, y)
    
    def move_snake(self):
        """Move snake in current direction"""
        if self.game_over or self.paused:
            return
        
        # Update direction
        self.direction = self.next_direction
        
        # Calculate new head position
        head_x, head_y = self.snake[-1]
        dx, dy = self.direction
        new_head = (head_x + dx, head_y + dy)
        
        # Check wall collision
        if (new_head[0] < 0 or new_head[0] >= GRID_SIZE or 
            new_head[1] < 0 or new_head[1] >= GRID_SIZE):
            self.game_over = True
            self.sound.sound_game_over()
            return
        
        # Check self collision
        if new_head in self.snake[:-1]:
            self.game_over = True
            self.sound.sound_game_over()
            return
        
        # Add new head
        self.snake.append(new_head)
        
        # Check food collision
        if new_head == self.food:
            self.score += 10
            self.sound.sound_eat()
            self.food = self.generate_food()
            
            # Update high score
            if self.score > self.high_score:
                self.high_score = self.score
            
            # Increase speed every 50 points
            new_level = (self.score // 50) + 1
            if new_level > self.speed_level:
                self.speed_level = new_level
                self.speed = max(MIN_SPEED, INITIAL_SPEED - (new_level - 1) * 25)
                self.sound.sound_level_up()
        else:
            # Remove tail if no food eaten
            self.snake.pop(0)
    
    def update_game(self):
        """Update game logic"""
        if self.game_over or self.paused:
            return
        
        current_time = utime.ticks_ms()
        
        # Move snake at current speed
        if utime.ticks_diff(current_time, self.last_move) >= self.speed:
            self.move_snake()
            self.last_move = current_time
    
    def draw_cell(self, x, y, color):
        """Draw a single grid cell"""
        pixel_x = BOARD_X + x * CELL_SIZE
        pixel_y = BOARD_Y + y * CELL_SIZE
        self.display.fill_rect(pixel_x + 1, pixel_y + 1, 
                              CELL_SIZE - 2, CELL_SIZE - 2, color)
    
    def draw_board(self):
        """Draw game board"""
        # Border
        border_x = BOARD_X - 1
        border_y = BOARD_Y - 1
        border_w = GRID_SIZE * CELL_SIZE + 1
        border_h = GRID_SIZE * CELL_SIZE + 1
        self.display.rect(border_x, border_y, border_w, border_h, COLOR_BORDER)
    
    def draw_snake(self):
        """Draw the snake"""
        # Draw body
        for i, segment in enumerate(self.snake[:-1]):
            self.draw_cell(segment[0], segment[1], COLOR_SNAKE_BODY)
        
        # Draw head (last segment) in brighter color
        if self.snake:
            head = self.snake[-1]
            self.draw_cell(head[0], head[1], COLOR_SNAKE_HEAD)
    
    def draw_food(self):
        """Draw food"""
        self.draw_cell(self.food[0], self.food[1], COLOR_FOOD)
    
    def draw_stats(self):
        """Draw score and stats"""
        # Only redraw if needed
        if self.needs_full_redraw or self.last_score != self.score:
            # Clear stats area
            self.display.fill_rect(0, 0, 320, 45, COLOR_BLACK)
            
            # Title
            title_text = "SNAKE"
            if not self.sound.sound_enabled:
                title_text += " [MUTE]"
            self.display.text(title_text, 10, 10, COLOR_TEXT)
            
            # Score on right side
            self.display.text(f"Score: {self.score}", 200, 10, COLOR_TEXT)
            self.display.text(f"High: {self.high_score}", 200, 22, COLOR_TEXT_DIM)
            self.display.text(f"Speed: {self.speed_level}", 200, 34, COLOR_TEXT_DIM)
            
            self.last_score = self.score
    
    def draw_controls(self):
        """Draw control hints"""
        if self.needs_full_redraw:
            # Position controls at the top, below the title and score
            controls_y = 22  # Position below title line
            
            self.display.text("Arrows: Move  P: Pause", 10, controls_y, COLOR_TEXT_DIM)
            self.display.text("S: Sound  ESC: Exit", 10, controls_y + 12, COLOR_TEXT_DIM)
    
    def draw_game_over(self):
        """Draw game over screen"""
        # Game over box
        box_x = self.width // 2 - 60
        box_y = self.height // 2 - 40
        box_w = 120
        box_h = 80
        
        self.display.fill_rect(box_x, box_y, box_w, box_h, COLOR_BLACK)
        self.display.rect(box_x, box_y, box_w, box_h, COLOR_WHITE)
        
        # Text
        self.display.text("GAME OVER", box_x + 20, box_y + 15, COLOR_WHITE)
        self.display.text(f"Score: {self.score}", box_x + 25, box_y + 35, COLOR_TEXT)
        self.display.text(f"Best: {self.high_score}", box_x + 25, box_y + 47, COLOR_TEXT)
        self.display.text("Any key...", box_x + 20, box_y + 59, COLOR_WHITE)
    
    def draw_pause(self):
        """Draw pause screen"""
        pause_x = self.width // 2 - 30
        pause_y = self.height // 2 - 10
        
        self.display.fill_rect(pause_x - 5, pause_y - 5, 70, 30, COLOR_BLACK)
        self.display.rect(pause_x - 5, pause_y - 5, 70, 30, COLOR_BORDER)
        self.display.text("PAUSED", pause_x, pause_y, COLOR_WHITE)
        self.display.text("P: Resume", pause_x - 3, pause_y + 12, COLOR_TEXT)
    
    def draw(self):
        """Draw everything"""
        # Only clear the game area to reduce flicker
        if not self.game_over and not self.paused:
            # Clear only the board area
            self.display.fill_rect(BOARD_X, BOARD_Y, 
                                 GRID_SIZE * CELL_SIZE, 
                                 GRID_SIZE * CELL_SIZE, COLOR_BLACK)
        else:
            # Full clear for overlays
            self.display.fill(0)
            self.needs_full_redraw = True
        
        self.draw_board()
        self.draw_snake()
        self.draw_food()
        self.draw_stats()
        self.draw_controls()
        
        if self.game_over:
            self.draw_game_over()
        elif self.paused:
            self.draw_pause()
        
        self.display.show()
        self.needs_full_redraw = False
    
    def handle_input(self):
        """Handle keyboard input"""
        if not picocalc.terminal:
            return False
        
        count = picocalc.terminal.readinto(self.key_buffer)
        if not count:
            return False
        
        key_data = bytes(self.key_buffer[:count])
        
        # ESC - exit
        if key_data == KEY_ESC:
            return "EXIT"
        
        # Game over state - any key restarts
        if self.game_over:
            if count == 1:
                # Any key press restarts the game
                self.reset_game()
            return True
        
        # Sound toggle
        if count == 1 and (self.key_buffer[0] == ord('s') or self.key_buffer[0] == ord('S')):
            enabled = self.sound.toggle_sound()
            print(f"Sound {'enabled' if enabled else 'disabled'}")
            return True
        
        # Pause
        if count == 1 and (self.key_buffer[0] == ord('p') or self.key_buffer[0] == ord('P')):
            self.paused = not self.paused
            return True
        
        if self.paused:
            return True
        
        # Movement (prevent 180 degree turns)
        if key_data == KEY_UP and self.direction != DIR_DOWN:
            self.next_direction = DIR_UP
            self.sound.sound_turn()
        elif key_data == KEY_DOWN and self.direction != DIR_UP:
            self.next_direction = DIR_DOWN
            self.sound.sound_turn()
        elif key_data == KEY_LEFT and self.direction != DIR_RIGHT:
            self.next_direction = DIR_LEFT
            self.sound.sound_turn()
        elif key_data == KEY_RIGHT and self.direction != DIR_LEFT:
            self.next_direction = DIR_RIGHT
            self.sound.sound_turn()
        
        return True
    
    def run(self):
        """Main game loop"""
        print("Starting Snake...")
        print("Use arrow keys to play, P to pause, ESC to exit")
        
        # Clear screen completely before starting game loop
        self.display.fill(COLOR_BLACK)
        self.display.show()
        
        try:
            while True:
                # Handle input
                result = self.handle_input()
                if result == "EXIT":
                    break
                
                # Update game
                self.update_game()
                
                # Draw
                self.draw()
                
                # Small delay
                utime.sleep_ms(20)
                
        except KeyboardInterrupt:
            print("Game interrupted")
        
        # Cleanup
        self.display.fill(COLOR_BLACK)
        self.display.text("Thanks for playing Snake!", 10, 10, COLOR_TEXT)
        self.display.show()
        utime.sleep(2)

def main():
    """Main function"""
    gc.collect()
    
    try:
        print(f"Free memory: {gc.mem_free()} bytes")
        game = SnakeGame()
        game.run()
        print("Snake exited normally")
    except Exception as e:
        print(f"Error: {e}")
        import sys
        sys.print_exception(e)

if __name__ == "__main__":
    main()