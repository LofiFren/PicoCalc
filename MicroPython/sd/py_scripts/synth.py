"""
Enhanced Synthesizer 3.0 for PicoCalc
Features:
- Headphone jack primary output with speaker toggle
- Advanced audio routing and volume control
- Enhanced waveform visualization
- Real-time audio monitoring
- Improved user interface with output selection
"""
import picocalc
import math
import utime
import gc
from machine import Pin, PWM

# Free up memory before starting
gc.collect()

# Audio pins for PicoCalc
AUDIO_LEFT = 28  # PWM_L - Primary stereo left
AUDIO_RIGHT = 27  # PWM_R - Primary stereo right

# Color definitions (4-bit grayscale for PicoCalc display)
COLOR_BLACK = 0
COLOR_DARK_GRAY = 4
COLOR_GRAY = 8
COLOR_LIGHT_GRAY = 12
COLOR_WHITE = 15

# Theme colors
COLOR_BACKGROUND = COLOR_BLACK
COLOR_BORDER = COLOR_LIGHT_GRAY
COLOR_HEADER = COLOR_WHITE
COLOR_TEXT = COLOR_WHITE
COLOR_TEXT_DIM = COLOR_GRAY
COLOR_HIGHLIGHT = COLOR_WHITE
COLOR_ACTIVE = COLOR_WHITE
COLOR_INACTIVE = COLOR_DARK_GRAY
COLOR_WAVEFORM = COLOR_LIGHT_GRAY
COLOR_GRID = COLOR_DARK_GRAY
COLOR_VU_NORMAL = COLOR_LIGHT_GRAY
COLOR_VU_PEAK = COLOR_WHITE
COLOR_HEADPHONE = COLOR_WHITE
COLOR_SPEAKER = COLOR_LIGHT_GRAY

# Define note frequencies (middle octave - 4)
BASE_NOTES = {
    'C': 262,
    'C#': 277,
    'D': 294,
    'D#': 311,
    'E': 330,
    'F': 349,
    'F#': 370,
    'G': 392,
    'G#': 415,
    'A': 440,
    'A#': 466,
    'B': 494
}

# Audio output modes
OUTPUT_HEADPHONE = 0
OUTPUT_SPEAKER = 1
OUTPUT_BOTH = 2

# Volume levels for different outputs
HEADPHONE_VOLUME = 0.7  # Lower volume for headphones (safer)
SPEAKER_VOLUME = 1.0    # Full volume for speakers
BOTH_VOLUME = 0.8       # Balanced volume for both

# Arrow key escape sequences for PicoCalc
KEY_UP = b'\x1b[A'      # Up arrow
KEY_DOWN = b'\x1b[B'    # Down arrow
KEY_LEFT = b'\x1b[D'    # Left arrow
KEY_RIGHT = b'\x1b[C'   # Right arrow
KEY_ESC = b'\x1b\x1b'   # Escape key (double ESC sequence)

class AdvancedSynth:
    def __init__(self):
        # Display setup
        self.display = picocalc.display
        self.width, self.height = self.display.width, self.display.height
        
        # Initialize audio PWM
        self.audio_left = PWM(Pin(AUDIO_LEFT))
        self.audio_right = PWM(Pin(AUDIO_RIGHT))
        
        # Audio output configuration
        self.output_mode = OUTPUT_HEADPHONE  # Default to headphone
        self.output_names = ["Headphone", "Speaker", "Both"]
        self.current_volume = HEADPHONE_VOLUME
        
        # Synth settings
        self.waveform = 0  # 0=square, 1=pulse, 2=saw, 3=triangle, 4=sine
        self.waveform_names = ["Square", "Pulse", "Saw", "Triangle", "Sine"]
        
        # Note and octave
        self.note_names = list(BASE_NOTES.keys())
        self.current_note_index = self.note_names.index('A')
        self.octave = 4
        
        # Current frequency
        self.frequency = BASE_NOTES[self.note_names[self.current_note_index]]
        
        # State
        self.is_playing = False
        self.use_detune = True
        self.detune_amount = 3
        self.pulse_width = 0.5
        self.master_volume = 0.8
        
        # Audio monitoring
        self.audio_level_left = 0.0
        self.audio_level_right = 0.0
        self.peak_hold_left = 0.0
        self.peak_hold_right = 0.0
        self.peak_timer = 0
        
        # Animation state
        self.animation_phase = 0
        self.last_update = utime.ticks_ms()
        
        # Input buffer
        self.key_buffer = bytearray(10)
        
        # Initialize display
        self.display.fill(COLOR_BACKGROUND)
        self.update_display()
        
        print("Advanced Synth 3.0 initialized")
        print(f"Audio output: {self.output_names[self.output_mode]}")
        print("Features: Audio routing, volume control, real-time monitoring")
    
    def set_output_mode(self, mode):
        """Set audio output mode and adjust volume accordingly"""
        self.output_mode = mode
        
        if mode == OUTPUT_HEADPHONE:
            self.current_volume = HEADPHONE_VOLUME
            print("🎧 Switched to Headphone output")
        elif mode == OUTPUT_SPEAKER:
            self.current_volume = SPEAKER_VOLUME
            print("🔊 Switched to Speaker output")
        elif mode == OUTPUT_BOTH:
            self.current_volume = BOTH_VOLUME
            print("🎵 Switched to Both outputs")
        
        # Update audio if currently playing
        if self.is_playing:
            self.update_audio_output()
        
        self.update_display()
    
    def cycle_output_mode(self):
        """Cycle through output modes"""
        self.output_mode = (self.output_mode + 1) % 3
        self.set_output_mode(self.output_mode)
    
    def update_frequency(self):
        """Calculate frequency based on note and octave"""
        base_freq = BASE_NOTES[self.note_names[self.current_note_index]]
        octave_diff = self.octave - 4
        self.frequency = base_freq * (2 ** octave_diff)
    
    def update_audio_output(self):
        """Update PWM audio output with current settings"""
        if not self.is_playing:
            return
        
        # Calculate effective volume
        effective_volume = self.master_volume * self.current_volume
        
        # Set frequencies
        left_freq = int(self.frequency)
        right_freq = int(self.frequency + (self.detune_amount if self.use_detune else 0))
        
        self.audio_left.freq(left_freq)
        self.audio_right.freq(right_freq)
        
        # Get duty cycle for waveform
        duty = self.get_duty_cycle()
        
        # Apply volume scaling
        scaled_duty_left = int(duty * effective_volume)
        scaled_duty_right = int(duty * effective_volume)
        
        # Apply output mode specific adjustments
        if self.output_mode == OUTPUT_HEADPHONE:
            # Slightly reduce high frequencies for headphone safety
            if self.frequency > 1000:
                scaled_duty_left = int(scaled_duty_left * 0.9)
                scaled_duty_right = int(scaled_duty_right * 0.9)
        elif self.output_mode == OUTPUT_SPEAKER:
            # Boost mid frequencies for speaker clarity
            if 200 <= self.frequency <= 800:
                scaled_duty_left = int(scaled_duty_left * 1.1)
                scaled_duty_right = int(scaled_duty_right * 1.1)
        
        # Set PWM duty cycles
        self.audio_left.duty_u16(min(65535, scaled_duty_left))
        self.audio_right.duty_u16(min(65535, scaled_duty_right))
        
        # Update audio level monitoring
        self.audio_level_left = effective_volume
        self.audio_level_right = effective_volume
    
    def update_display(self):
        """Update display with enhanced visuals"""
        self.display.beginDraw()
        self.display.fill(COLOR_BACKGROUND)
        
        # Enhanced header with output indicator
        self.draw_header()
        
        # Audio output selection panel
        self.draw_output_panel()
        
        # Enhanced info panel
        self.draw_info_panel()
        
        # Waveform visualization
        self.draw_enhanced_waveform()
        
        # Audio level meters
        self.draw_audio_meters()
        
        # Enhanced controls
        self.draw_controls()
        
        # Show the display
        self.display.show()
    
    def draw_header(self):
        """Draw header with output mode indicator"""
        # Outer border
        self.display.rect(0, 0, self.width, 25, COLOR_BORDER)
        self.display.rect(1, 1, self.width-2, 23, COLOR_HIGHLIGHT)
        
        # Title with animation
        title = "♪ SYNTH 3.0 ♪"
        if self.is_playing:
            # Animate title when playing
            phase = int(self.animation_phase / 10) % 3
            if phase == 1:
                title = "♫ SYNTH 3.0 ♫"
            elif phase == 2:
                title = "♬ SYNTH 3.0 ♬"
        
        self.display.text(title, 5, 7, COLOR_HEADER)
        
        # Output mode indicator
        mode_x = self.width - 80
        mode_color = COLOR_HEADPHONE if self.output_mode == OUTPUT_HEADPHONE else COLOR_SPEAKER
        if self.output_mode == OUTPUT_BOTH:
            mode_color = COLOR_ACTIVE
        
        mode_icon = "🎧" if self.output_mode == OUTPUT_HEADPHONE else ("🔊" if self.output_mode == OUTPUT_SPEAKER else "🎵")
        self.display.text(mode_icon, mode_x, 7, mode_color)
        self.display.text(self.output_names[self.output_mode], mode_x + 15, 7, mode_color)
    
    def draw_output_panel(self):
        """Draw audio output selection panel"""
        y_start = 30
        
        # Output selection box
        self.display.rect(5, y_start, 100, 20, COLOR_BORDER)
        self.display.text("OUTPUT", 8, y_start + 3, COLOR_TEXT_DIM)
        
        # Volume indicator
        vol_width = int(85 * self.current_volume)
        self.display.fill_rect(8, y_start + 12, vol_width, 3, COLOR_ACTIVE)
        self.display.rect(8, y_start + 12, 85, 3, COLOR_BORDER)
        
        # Volume percentage
        vol_text = f"{int(self.current_volume * 100)}%"
        self.display.text(vol_text, 65, y_start + 3, COLOR_TEXT)
    
    def draw_info_panel(self):
        """Draw enhanced info panel"""
        y_start = 55
        
        # Note display
        note_name = self.note_names[self.current_note_index]
        note_text = f"{note_name}{self.octave}"
        
        self.display.rect(5, y_start, 70, 25, COLOR_BORDER)
        self.display.text("NOTE", 8, y_start + 3, COLOR_TEXT_DIM)
        
        # Large note text
        note_color = COLOR_HIGHLIGHT if self.is_playing else COLOR_TEXT
        for dx in range(2):
            for dy in range(2):
                self.display.text(note_text, 12 + dx, y_start + 12 + dy, note_color)
        
        # Frequency display with color coding
        freq_text = f"{int(self.frequency)}Hz"
        self.display.rect(80, y_start, 70, 25, COLOR_BORDER)
        self.display.text("FREQ", 83, y_start + 3, COLOR_TEXT_DIM)
        
        # Color code frequency
        if self.frequency < 300:
            freq_color = COLOR_GRAY  # Low
        elif self.frequency < 600:
            freq_color = COLOR_TEXT  # Mid
        else:
            freq_color = COLOR_HIGHLIGHT  # High
            
        self.display.text(freq_text, 85, y_start + 15, freq_color)
        
        # Waveform name
        wf_name = self.waveform_names[self.waveform]
        self.display.rect(155, y_start, 70, 25, COLOR_BORDER)
        self.display.text("WAVE", 158, y_start + 3, COLOR_TEXT_DIM)
        self.display.text(wf_name, 160, y_start + 15, COLOR_TEXT)
        
        # Effects and status
        self.display.rect(230, y_start, 70, 25, COLOR_BORDER)
        self.display.text("STATUS", 233, y_start + 3, COLOR_TEXT_DIM)
        if self.is_playing:
            self.display.text("PLAYING", 235, y_start + 15, COLOR_ACTIVE)
        else:
            self.display.text("STOPPED", 235, y_start + 15, COLOR_INACTIVE)
    
    def draw_enhanced_waveform(self):
        """Draw enhanced waveform with better graphics"""
        x, y = 10, 85
        width, height = 290, 50
        
        # Draw frame
        self.display.rect(x-2, y-2, width+4, height+4, COLOR_BORDER)
        self.display.rect(x-1, y-1, width+2, height+2, COLOR_HIGHLIGHT)
        
        # Grid lines
        middle_y = y + height // 2
        self.display.hline(x, middle_y, width, COLOR_GRID)
        for i in range(0, width, 40):
            self.display.vline(x + i, y, height, COLOR_GRID)
        
        # Draw waveform based on type
        if self.waveform == 0:  # Square
            self.draw_square_wave(x, y, width, height)
        elif self.waveform == 1:  # Pulse
            self.draw_pulse_wave(x, y, width, height)
        elif self.waveform == 2:  # Sawtooth
            self.draw_saw_wave(x, y, width, height)
        elif self.waveform == 3:  # Triangle
            self.draw_triangle_wave(x, y, width, height)
        elif self.waveform == 4:  # Sine
            self.draw_sine_wave(x, y, width, height)
    
    def draw_square_wave(self, x, y, width, height):
        """Enhanced square wave"""
        middle_y = y + height // 2
        segment = 30
        offset = int(self.animation_phase / 2) % segment if self.is_playing else 0
        
        for i in range(-offset, width + segment, segment):
            if i >= width:
                break
            half = segment // 2
            
            # Draw thick square wave
            for t in range(2):
                if i + half < width:
                    self.display.hline(x + i, y + 10 + t, half, COLOR_WAVEFORM)
                self.display.vline(x + i + half, y + 10, height - 20, COLOR_WAVEFORM)
                if i + segment < width:
                    self.display.hline(x + i + half, middle_y + 10 + t, half, COLOR_WAVEFORM)
    
    def draw_pulse_wave(self, x, y, width, height):
        """Enhanced pulse wave"""
        middle_y = y + height // 2
        segment = 30
        pulse = int(segment * self.pulse_width)
        offset = int(self.animation_phase / 2) % segment if self.is_playing else 0
        
        for i in range(-offset, width + segment, segment):
            if i >= width:
                break
            for t in range(2):
                self.display.hline(x + i, y + 10 + t, pulse, COLOR_WAVEFORM)
                self.display.hline(x + i + pulse, middle_y + 10 + t, segment - pulse, COLOR_WAVEFORM)
            self.display.vline(x + i + pulse, y + 10, height - 20, COLOR_WAVEFORM)
    
    def draw_saw_wave(self, x, y, width, height):
        """Enhanced sawtooth wave"""
        segment = 30
        offset = int(self.animation_phase / 2) % segment if self.is_playing else 0
        
        for i in range(-offset, width + segment, segment):
            if i >= width:
                break
            for t in range(2):
                start_y = y + height - 10 + t
                end_y = y + 10 + t
                self.display.line(x + i, start_y, x + i + segment, end_y, COLOR_WAVEFORM)
                if i + segment < width:
                    self.display.vline(x + i + segment, end_y, start_y - end_y, COLOR_WAVEFORM)
    
    def draw_triangle_wave(self, x, y, width, height):
        """Enhanced triangle wave"""
        segment = 30
        half = segment // 2
        offset = int(self.animation_phase / 2) % segment if self.is_playing else 0
        
        for i in range(-offset, width + segment, segment):
            if i >= width:
                break
            for t in range(2):
                mid_y = y + height // 2 + t
                top_y = y + 10 + t
                self.display.line(x + i, mid_y, x + i + half, top_y, COLOR_WAVEFORM)
                self.display.line(x + i + half, top_y, x + i + segment, mid_y, COLOR_WAVEFORM)
    
    def draw_sine_wave(self, x, y, width, height):
        """Enhanced animated sine wave"""
        middle_y = y + height // 2
        prev_points = []
        
        for i in range(width):
            angle = (i / width) * 4 * math.pi + (self.animation_phase / 10.0 if self.is_playing else 0)
            value = math.sin(angle)
            curr_y = int(middle_y + value * (height // 2 - 8))
            prev_points.append((x + i, curr_y))
        
        for i in range(len(prev_points) - 1):
            x1, y1 = prev_points[i]
            x2, y2 = prev_points[i + 1]
            for t in range(2):
                self.display.line(x1, y1 + t, x2, y2 + t, COLOR_WAVEFORM)
    
    def draw_audio_meters(self):
        """Draw stereo audio level meters"""
        x, y = 10, 140
        width, height = 290, 25
        
        # Meter background
        self.display.rect(x, y, width, height, COLOR_BORDER)
        self.display.text("AUDIO LEVELS", x + 5, y + 3, COLOR_TEXT_DIM)
        
        # Left channel meter
        left_x = x + 10
        left_width = int((width - 40) / 2)
        self.display.text("L", left_x - 8, y + 15, COLOR_TEXT_DIM)
        self.display.rect(left_x, y + 12, left_width, 8, COLOR_BORDER)
        
        if self.is_playing:
            level = int(left_width * self.audio_level_left)
            level_color = COLOR_VU_PEAK if self.audio_level_left > 0.8 else COLOR_VU_NORMAL
            self.display.fill_rect(left_x + 1, y + 13, level, 6, level_color)
        
        # Right channel meter
        right_x = left_x + left_width + 10
        self.display.text("R", right_x - 8, y + 15, COLOR_TEXT_DIM)
        self.display.rect(right_x, y + 12, left_width, 8, COLOR_BORDER)
        
        if self.is_playing:
            level = int(left_width * self.audio_level_right)
            level_color = COLOR_VU_PEAK if self.audio_level_right > 0.8 else COLOR_VU_NORMAL
            self.display.fill_rect(right_x + 1, y + 13, level, 6, level_color)
    
    def draw_controls(self):
        """Draw enhanced control help"""
        y_start = 170
        
        # Control box
        self.display.rect(5, y_start, self.width - 10, 120, COLOR_BORDER)
        self.display.text("CONTROLS", 10, y_start + 5, COLOR_HEADER)
        
        # Enhanced controls list
        controls_left = [
            "◄►: Note",
            "▲▼: Octave", 
            "W: Waveform",
            "P: Play/Stop",
            "O: Output Mode"
        ]
        
        controls_right = [
            "D: Detune",
            "V: Volume",
            "1-7: Direct",
            "ESC: Exit",
            ""
        ]
        
        for i, (left, right) in enumerate(zip(controls_left, controls_right)):
            y_pos = y_start + 20 + i * 12
            self.display.text(left, 10, y_pos, COLOR_TEXT_DIM)
            if right:
                self.display.text(right, 160, y_pos, COLOR_TEXT_DIM)
    
    def get_duty_cycle(self):
        """Get PWM duty cycle for current waveform"""
        if self.waveform == 0:  # Square
            return 32768  # 50% duty
        elif self.waveform == 1:  # Pulse
            return int(65535 * self.pulse_width)
        elif self.waveform == 2:  # Sawtooth
            return 55000  # Approximation
        elif self.waveform == 3:  # Triangle
            return 32768  # 50% duty
        elif self.waveform == 4:  # Sine
            return 32768  # Will be modulated
        return 32768
    
    def play_note(self):
        """Play current note"""
        self.is_playing = True
        self.update_audio_output()
        
        note = self.note_names[self.current_note_index]
        output = self.output_names[self.output_mode]
        print(f"♪ Playing {note}{self.octave} ({int(self.frequency)} Hz) via {output}")
        self.update_display()
    
    def stop_note(self):
        """Stop playback"""
        self.audio_left.duty_u16(0)
        self.audio_right.duty_u16(0)
        self.is_playing = False
        self.audio_level_left = 0.0
        self.audio_level_right = 0.0
        print("♪ Sound stopped")
        self.update_display()
    
    def toggle_note(self):
        """Toggle between play and stop"""
        if self.is_playing:
            self.stop_note()
        else:
            self.play_note()
    
    def adjust_volume(self, delta):
        """Adjust master volume"""
        self.master_volume = max(0.1, min(1.0, self.master_volume + delta))
        if self.is_playing:
            self.update_audio_output()
        self.update_display()
        print(f"Volume: {int(self.master_volume * 100)}%")
    
    def next_note(self):
        """Change to next note"""
        self.current_note_index = (self.current_note_index + 1) % len(self.note_names)
        self.update_frequency()
        if self.is_playing:
            self.play_note()
        else:
            self.update_display()
    
    def prev_note(self):
        """Change to previous note"""
        self.current_note_index = (self.current_note_index - 1) % len(self.note_names)
        self.update_frequency()
        if self.is_playing:
            self.play_note()
        else:
            self.update_display()
    
    def octave_up(self):
        """Increase octave"""
        if self.octave < 7:
            self.octave += 1
            self.update_frequency()
            if self.is_playing:
                self.play_note()
            else:
                self.update_display()
    
    def octave_down(self):
        """Decrease octave"""
        if self.octave > 1:
            self.octave -= 1
            self.update_frequency()
            if self.is_playing:
                self.play_note()
            else:
                self.update_display()
    
    def cycle_waveform(self):
        """Change to next waveform"""
        self.waveform = (self.waveform + 1) % len(self.waveform_names)
        if self.is_playing:
            self.play_note()
        else:
            self.update_display()
    
    def toggle_detune(self):
        """Toggle stereo detune effect"""
        self.use_detune = not self.use_detune
        if self.is_playing:
            self.update_audio_output()
        self.update_display()
    
    def handle_input(self):
        """Process keyboard input"""
        if not picocalc.terminal:
            return False
        
        count = picocalc.terminal.readinto(self.key_buffer)
        if not count:
            return False
        
        key_data = bytes(self.key_buffer[:count])
        
        # Check for ESC key (exit)
        if key_data == KEY_ESC or (count == 1 and self.key_buffer[0] == 0x1b):
            self.exit_synth()
            return "EXIT"
        
        # Handle arrow keys
        if key_data == KEY_LEFT:
            self.prev_note()
            return True
        elif key_data == KEY_RIGHT:
            self.next_note()
            return True
        elif key_data == KEY_UP:
            self.octave_up()
            return True
        elif key_data == KEY_DOWN:
            self.octave_down()
            return True
        
        # Handle other keys
        if count == 1:
            key = self.key_buffer[0]
            
            # Play/Stop
            if key == ord('p') or key == ord('P'):
                self.toggle_note()
                return True
            
            # Output mode toggle
            if key == ord('o') or key == ord('O'):
                self.cycle_output_mode()
                return True
            
            # Volume control
            if key == ord('v') or key == ord('V'):
                self.adjust_volume(0.1)
                return True
            if key == ord('b') or key == ord('B'):
                self.adjust_volume(-0.1)
                return True
            
            # Toggle detune
            if key == ord('d') or key == ord('D'):
                self.toggle_detune()
                return True
            
            # Change waveform
            if key == ord('w') or key == ord('W'):
                self.cycle_waveform()
                return True
            
            # Direct note selection
            if key >= ord('1') and key <= ord('7'):
                note_idx = key - ord('1')
                if note_idx < len(self.note_names):
                    self.current_note_index = note_idx
                    self.update_frequency()
                    if self.is_playing:
                        self.play_note()
                    else:
                        self.update_display()
                    return True
        
        return True
    
    def exit_synth(self):
        """Clean up before exiting"""
        if self.is_playing:
            self.stop_note()

        self.display.fill(COLOR_BACKGROUND)
        self.display.text("Exiting Advanced Synthesizer...", 10, 10, COLOR_TEXT)
        self.display.show()

        print("Exiting Advanced Synthesizer 3.0...")
        utime.sleep(1)
    
    def update_animation(self):
        """Update animation states"""
        current_time = utime.ticks_ms()
        
        if current_time - self.last_update > 50:  # 20 FPS
            self.animation_phase += 1
            if self.animation_phase > 1000:
                self.animation_phase = 0
            
            # Update audio level simulation
            if self.is_playing:
                # Simulate dynamic audio levels
                base_level = self.current_volume * self.master_volume
                variation = 0.1 * math.sin(current_time / 150.0)
                self.audio_level_left = max(0.1, min(1.0, base_level + variation))
                self.audio_level_right = max(0.1, min(1.0, base_level + variation * 0.8))
            
            # Refresh display for animations
            if self.is_playing or (current_time - self.last_update) > 200:
                self.update_display()
            
            self.last_update = current_time
    
    def run(self):
        """Main synthesizer loop"""
        print("Starting Advanced Synthesizer 3.0...")
        print("Audio output defaulted to Headphone jack")
        print("Press 'O' to switch output modes, ESC to exit")
        
        # Play a brief test note
        print("Playing test note (A4)...")
        self.play_note()
        utime.sleep(0.5)
        self.stop_note()
        
        try:
            while True:
                # Check for keyboard input
                result = self.handle_input()
                if result == "EXIT":
                    break
                
                # Animation and visual updates
                self.update_animation()
                
                # Sine wave modulation
                if self.is_playing and self.waveform == 4:
                    t = utime.ticks_ms() / 500.0
                    sine_val = math.sin(2 * math.pi * t * 2)
                    
                    # Apply volume scaling
                    effective_volume = self.master_volume * self.current_volume
                    duty = int(32768 + sine_val * 32767 * effective_volume)
                    
                    self.audio_left.duty_u16(min(65535, duty))
                    
                    # Right channel with slight phase offset and detune
                    sine_val_r = math.sin(2 * math.pi * t * 2 + 0.2)
                    duty_r = int(32768 + sine_val_r * 32767 * effective_volume)
                    self.audio_right.duty_u16(min(65535, duty_r))
                
                utime.sleep_ms(10)
                
        except KeyboardInterrupt:
            self.stop_note()
            print("Synthesizer stopped")
        
        self.stop_note()
        return

def main():
    """Main function"""
    gc.collect()
    
    try:
        free = gc.mem_free()
        print(f"Free memory: {free} bytes")
        
        synth = AdvancedSynth()
        synth.run()
        print("Advanced Synthesizer 3.0 exited normally")
    except Exception as e:
        print(f"Error: {e}")
        import sys
        sys.print_exception(e)

if __name__ == "__main__":
    main()