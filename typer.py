#!/usr/bin/env python3
"""
Typeracer CLI - Minimal typing speed game with rewards
Requires full accuracy to complete each quote
"""

import sys
import time
import random
import csv
import curses
import unicodedata
from datetime import datetime
from pathlib import Path


# =============================================================================
# GAMIFICATION CONFIG - Easy to adjust!
# =============================================================================
class RewardConfig:
    """Configure reward tiers and thresholds here"""
    
    # WPM Thresholds
    PRISTINE_WPM = 90      # WPM needed for Pristine tier
    EXCEPTIONAL_WPM = 80   # WPM needed for Exceptional tier
    ADEQUATE_WPM = 70      # WPM needed for Adequate tier
    # Below ADEQUATE_WPM = Disaster tier
    
    # Error Thresholds
    PRISTINE_MAX_ERRORS = 0  # Maximum errors allowed for Pristine tier
    
    # Reward Tier Definitions
    TIERS = {
        'pristine': {
            'name': 'PRISTINE',
            'color': 6,  # Magenta - most rare
            'symbol': '◆',
            'description': 'flawless',
            'requires_wpm': PRISTINE_WPM,
            'requires_max_errors': PRISTINE_MAX_ERRORS
        },
        'exceptional': {
            'name': 'EXCEPTIONAL',
            'color': 5,  # Yellow - rare
            'symbol': '★',
            'description': 'outstanding performance',
            'requires_wpm': EXCEPTIONAL_WPM,
            'requires_max_errors': None  # No error limit
        },
        'adequate': {
            'name': 'ADEQUATE',
            'color': 4,  # Cyan - good
            'symbol': '●',
            'description': 'solid typing',
            'requires_wpm': ADEQUATE_WPM,
            'requires_max_errors': None
        },
        'disaster': {
            'name': 'DISASTER',
            'color': 2,  # Red - needs improvement
            'symbol': '▼',
            'description': 'room for growth',
            'requires_wpm': 0,  # Anything below ADEQUATE_WPM
            'requires_max_errors': None
        }
    }


class TyperacerGame:
    def __init__(self):
        self.quotes_dir = Path("quotes")
        self.stats_file = Path("typing_stats.csv")
        self.quote = ""
        self.quote_metadata = ""
        self.typed_text = ""
        self.start_time = None
        self.end_time = None
        self.errors = 0
        self.session_stats = []
        self.initialize_stats_file()

        # Translation table for normalizing quotes
        # Use Unicode code points directly
        self.quote_normalization_table = str.maketrans({
            0x201C: '"',  # " Left double quote
            0x201D: '"',  # " Right double quote
            0x2018: "'",  # ' Left single quote
            0x2019: "'",  # ' Right single quote
        })        
    
    def normalize_text(self, text):
        """Normalize different kinds of quotes to standard ones."""
        return text.translate(self.quote_normalization_table)
    
    def normalize_accents(self, text):
        """Remove accents from characters (e.g., ö -> o, é -> e)"""
        # Decompose unicode characters into base + combining characters
        nfd = unicodedata.normalize('NFD', text)
        # Filter out combining characters (accents)
        without_accents = ''.join(char for char in nfd if unicodedata.category(char) != 'Mn')
        return without_accents

    def initialize_stats_file(self):
        """Create stats CSV file if it doesn't exist"""
        if not self.stats_file.exists():
            with open(self.stats_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['timestamp', 'date', 'time', 'wpm', 'accuracy', 'errors', 'duration_seconds', 'tier'])
    
    def calculate_tier(self, wpm, errors):
        """Determine the reward tier based on performance"""
        # Check for Pristine first (highest tier)
        if wpm >= RewardConfig.PRISTINE_WPM and errors <= RewardConfig.PRISTINE_MAX_ERRORS:
            return 'pristine'
        # Check for Exceptional
        elif wpm >= RewardConfig.EXCEPTIONAL_WPM:
            return 'exceptional'
        # Check for Adequate
        elif wpm >= RewardConfig.ADEQUATE_WPM:
            return 'adequate'
        # Otherwise it's Disaster
        else:
            return 'disaster'
    
    def save_stats(self, wpm, elapsed_time, tier):
        """Save stats to CSV file"""
        now = datetime.now()
        with open(self.stats_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                now.isoformat(),
                now.strftime('%Y-%m-%d'),
                now.strftime('%H:%M:%S'),
                wpm,
                100.0,  # Always 100% accuracy now
                self.errors,
                round(elapsed_time, 2),
                tier
            ])
    
    def get_historical_stats(self):
        """Get historical statistics from CSV"""
        if not self.stats_file.exists():
            return None
        
        try:
            with open(self.stats_file, 'r') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                
            if len(rows) == 0:
                return None
            
            wpms = [float(row['wpm']) for row in rows]
            recent_wpms = wpms[-5:] if len(wpms) > 5 else wpms
            
            # Count tier achievements
            tier_counts = {}
            for row in rows:
                tier = row.get('tier', 'unknown')
                tier_counts[tier] = tier_counts.get(tier, 0) + 1
            
            return {
                'total_rounds': len(rows),
                'avg_wpm': round(sum(wpms) / len(wpms), 1),
                'recent_avg_wpm': round(sum(recent_wpms) / len(recent_wpms), 1),
                'best_wpm': round(max(wpms), 1),
                'tier_counts': tier_counts
            }
        except:
            return None
    
    def parse_metadata(self, lines):
        """Parse metadata from the second line of quote file"""
        if len(lines) < 2:
            return ""
        
        metadata_line = lines[1].strip()
        if not metadata_line:
            return ""
        
        # Parse [[BOOK: ...]][[AUTHOR: ...]] format
        import re
        parts = []
        
        book_match = re.search(r'\[\[BOOK:\s*([^\]]+)\]\]', metadata_line)
        if book_match:
            parts.append(book_match.group(1).strip())
        
        author_match = re.search(r'\[\[AUTHOR:\s*([^\]]+)\]\]', metadata_line)
        if author_match:
            parts.append(author_match.group(1).strip())
        
        return " · ".join(parts) if parts else ""
    
    def load_quotes(self):
        quote_files = list(self.quotes_dir.glob("*.txt"))
        if not quote_files:
            raise FileNotFoundError("No quote files found in quotes directory")
        
        selected_file = random.choice(quote_files)
        lines = selected_file.read_text().strip().split('\n')
        
        raw_quote = lines[0].strip()
        self.quote = self.normalize_text(raw_quote)
        self.quote_metadata = self.parse_metadata(lines)

    def calculate_wpm(self):
        """Calculate Words Per Minute"""
        if not self.start_time or len(self.typed_text) == 0:
            return 0.0
        
        elapsed_time = time.time() - self.start_time
        if elapsed_time == 0:
            return 0.0
        
        minutes = elapsed_time / 60
        wpm = (len(self.typed_text) / 5) / minutes
        return round(wpm, 1)
    
    def is_complete(self):
        """Check if quote is typed correctly and completely"""
        # First check if lengths match
        if len(self.typed_text) != len(self.quote):
            return False
        
        # Compare character by character with accent normalization
        for i in range(len(self.quote)):
            typed_char = self.normalize_accents(self.typed_text[i])
            quote_char = self.normalize_accents(self.quote[i])
            if typed_char != quote_char:
                return False
        
        return True
    
    def reset_for_new_round(self):
        """Reset game state for a new round"""
        self.typed_text = ""
        self.start_time = None
        self.end_time = None
        self.errors = 0


class CursesUI:
    """Handles all curses-based UI rendering"""
    
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.height, self.width = stdscr.getmaxyx()
        
        # Initialize colors
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_GREEN, -1)     # Correct text
        curses.init_pair(2, curses.COLOR_RED, -1)       # Error text
        curses.init_pair(3, curses.COLOR_WHITE, -1)     # Untyped text
        curses.init_pair(4, curses.COLOR_CYAN, -1)      # Stats
        curses.init_pair(5, curses.COLOR_YELLOW, -1)    # WPM
        curses.init_pair(6, curses.COLOR_MAGENTA, -1)   # Pristine tier
        
        # Hide cursor
        curses.curs_set(0)
        
        self.stdscr.nodelay(False)
        self.stdscr.keypad(True)
    
    def center_text(self, y, text, attr=0):
        """Print centered text at given y coordinate"""
        if y >= self.height or y < 0:
            return
        x = max(0, (self.width - len(text)) // 2)
        try:
            self.stdscr.addstr(y, x, text[:self.width], attr)
        except curses.error:
            pass
    
    def render_welcome_screen(self, game):
        """Display minimal welcome screen"""
        self.stdscr.clear()
        y = self.height // 2 - 4
        
        self.center_text(y, "TYPERACER", curses.A_BOLD)
        y += 2
        
        hist_stats = game.get_historical_stats()
        if hist_stats:
            self.center_text(y, f"avg {hist_stats['avg_wpm']} wpm  ·  best {hist_stats['best_wpm']} wpm", curses.color_pair(4))
            y += 1
            
            # Show tier achievements if available
            tier_counts = hist_stats.get('tier_counts', {})
            if tier_counts:
                tier_display = []
                if tier_counts.get('pristine', 0) > 0:
                    tier_display.append(f"{RewardConfig.TIERS['pristine']['symbol']} {tier_counts['pristine']}")
                if tier_counts.get('exceptional', 0) > 0:
                    tier_display.append(f"{RewardConfig.TIERS['exceptional']['symbol']} {tier_counts['exceptional']}")
                
                if tier_display:
                    self.center_text(y, " · ".join(tier_display), curses.A_DIM)
                    y += 1
            
            self.center_text(y, f"{hist_stats['total_rounds']} rounds completed", curses.A_DIM)
        else:
            self.center_text(y, "Type each quote with perfect accuracy", curses.A_DIM)
        
        y += 3
        self.center_text(y, "press any key to start", curses.A_DIM)
        
        self.stdscr.refresh()
        self.stdscr.getch()
    
    def wrap_text_preserve_chars(self, text, width):
        """Wrap text at word boundaries without breaking words"""
        if not text:
            return []
        
        lines = []
        words = text.split(' ')
        current_line = ""
        
        for i, word in enumerate(words):
            # Check if this is the first word on the line
            if not current_line:
                # Start a new line with this word
                if len(word) <= width:
                    current_line = word
                else:
                    # Word is too long, must break it
                    while len(word) > width:
                        lines.append(word[:width])
                        word = word[width:]
                    current_line = word
            else:
                # Try adding word with a space
                test_line = current_line + ' ' + word
                if len(test_line) <= width:
                    current_line = test_line
                else:
                    # Can't fit, save current line and start new one
                    lines.append(current_line)
                    if len(word) <= width:
                        current_line = word
                    else:
                        # Word is too long, must break it
                        while len(word) > width:
                            lines.append(word[:width])
                            word = word[width:]
                        current_line = word
        
        # Don't forget the last line
        if current_line:
            lines.append(current_line)
        
        return lines
    
    def render_game_screen(self, game):
        """Render minimal game screen"""
        self.stdscr.clear()
        
        wrap_width = max(10, self.width - 10)
        
        # Wrap text preserving character count
        quote_lines = self.wrap_text_preserve_chars(game.quote, wrap_width)

        num_quote_lines = len(quote_lines)
        
        # Calculate vertical center for the entire game display block
        block_height = num_quote_lines + 4  # Quote lines + WPM + metadata
        start_y = max(0, (self.height - block_height) // 2)
        
        # WPM display at top
        wpm = game.calculate_wpm()
        if wpm > 0:
            self.center_text(start_y, f"{wpm} wpm", curses.color_pair(5))
        
        # Render quote
        self.render_quote(start_y + 2, game, quote_lines)
        
        # Show metadata instead of progress counter
        if game.quote_metadata:
            self.center_text(start_y + 2 + num_quote_lines + 1, game.quote_metadata, curses.A_DIM)
        
        self.stdscr.refresh()

    def render_quote(self, start_y, game, quote_lines):
        """Render the quote with color-coded characters"""
        char_index = 0
        
        for i, line in enumerate(quote_lines):
            y = start_y + i
            if y >= self.height:
                break
            
            start_x = max(0, (self.width - len(line)) // 2)
            
            # Render each character from the original quote
            for j in range(len(line)):
                if char_index >= len(game.quote):
                    break
                    
                x = start_x + j
                if x >= self.width:
                    break
                
                quote_char = game.quote[char_index]
                
                try:
                    if char_index < len(game.typed_text):
                        # Normalize both for comparison (handles accents)
                        typed_normalized = game.normalize_accents(game.typed_text[char_index])
                        quote_normalized = game.normalize_accents(quote_char)
                        
                        if typed_normalized == quote_normalized:
                            # Correct character
                            self.stdscr.addstr(y, x, quote_char, curses.color_pair(1))
                        else:
                            # Incorrect character
                            self.stdscr.addstr(y, x, quote_char, curses.color_pair(2) | curses.A_BOLD)
                    else:
                        # Not yet typed
                        self.stdscr.addstr(y, x, quote_char, curses.color_pair(3) | curses.A_DIM)
                except curses.error:
                    pass
                
                char_index += 1
            
            # Add space between words (the space that was removed by split)
            # But only if we're not at the last line
            if i < len(quote_lines) - 1 and char_index < len(game.quote):
                if game.quote[char_index] == ' ':
                    char_index += 1

    def render_completion_screen(self, game, wpm, elapsed_time, tier):
        """Display completion for current round with reward tier"""
        self.stdscr.clear()
        
        tier_info = RewardConfig.TIERS[tier]
        
        y = self.height // 2 - 5
        
        # Display tier symbol with extra spacing for rare tiers
        symbol_line = tier_info['symbol']
        if tier in ['pristine', 'exceptional']:
            symbol_line = f"  {tier_info['symbol']}  {tier_info['symbol']}  {tier_info['symbol']}  "
        
        self.center_text(y, symbol_line, curses.color_pair(tier_info['color']) | curses.A_BOLD)
        y += 1
        
        # Display tier name
        tier_attr = curses.color_pair(tier_info['color']) | curses.A_BOLD
        if tier == 'pristine':
            tier_attr |= curses.A_REVERSE  # Extra emphasis for pristine
        
        self.center_text(y, tier_info['name'], tier_attr)
        y += 1
        
        # Display description
        self.center_text(y, tier_info['description'], curses.A_DIM)
        y += 2
        
        # Display stats
        stats_text = f"{wpm} wpm  ·  {elapsed_time:.1f}s"
        self.center_text(y, stats_text, curses.color_pair(4))
        
        if game.errors > 0:
            y += 1
            error_text = f"{game.errors} corrected"
            self.center_text(y, error_text, curses.A_DIM)

        
        y += 2
        self.center_text(y, "press any key to continue", curses.A_DIM)
        
        self.stdscr.refresh()
        self.stdscr.getch()
    
    def render_session_summary(self, game):
        """Display session summary on exit"""
        self.stdscr.clear()
        y = self.height // 2 - 4
        
        self.center_text(y, "SESSION COMPLETE", curses.A_BOLD)
        y += 2
        
        if game.session_stats:
            total_rounds = len(game.session_stats)
            avg_wpm = sum(s['wpm'] for s in game.session_stats) / total_rounds
            best_wpm = max(s['wpm'] for s in game.session_stats)
            
            self.center_text(y, f"{total_rounds} rounds  ·  {avg_wpm:.1f} avg wpm  ·  {best_wpm:.1f} best", curses.color_pair(4))
            
            # Show tier breakdown for session
            y += 1
            tier_counts = {}
            for stat in game.session_stats:
                tier = stat.get('tier', 'unknown')
                tier_counts[tier] = tier_counts.get(tier, 0) + 1
            
            tier_display = []
            for tier_key in ['pristine', 'exceptional', 'adequate', 'disaster']:
                count = tier_counts.get(tier_key, 0)
                if count > 0:
                    symbol = RewardConfig.TIERS[tier_key]['symbol']
                    tier_display.append(f"{symbol} {count}")
            
            if tier_display:
                self.center_text(y, " · ".join(tier_display), curses.A_DIM)
        
        y += 3
        self.center_text(y, "thanks for playing", curses.A_DIM)
        
        self.stdscr.refresh()
        time.sleep(2)


def main_curses(stdscr):
    """Main game loop with curses"""
    ui = CursesUI(stdscr)
    game = TyperacerGame()
    
    try:
        ui.render_welcome_screen(game)
        
        while True:
            game.load_quotes()
            game.reset_for_new_round()
            
            # Initial render
            ui.render_game_screen(game)
            
            last_wpm = 0
            
            # Game loop for this quote - continues until perfect match
            while not game.is_complete():
                try:
                    ch = stdscr.getch()
                except KeyboardInterrupt:
                    raise
                
                should_render = False
                
                # Handle input
                if ch in (curses.KEY_BACKSPACE, 127, 8):  # Backspace
                    if len(game.typed_text) > 0:
                        game.typed_text = game.typed_text[:-1]
                        should_render = True
                        
                elif ch == 3:  # Ctrl+C
                    raise KeyboardInterrupt
                
                # MODIFICATION: Added shortcut to end the typing phase
                elif ch == 24: # CTRL+X shortcut
                    # This ends the round, calculating stats based on progress.
                    # CTRL+. was requested, but it's not a standard key code.
                    # CTRL+X (ASCII 24) is a reliable alternative.
                    # To use a different key, change the value '24'.
                    if game.start_time is None:
                        game.start_time = time.time() # Ensure timer has started
                    break # Exit the typing loop

                elif 32 <= ch <= 126:  # Printable ASCII
                    # Start timer on first character
                    if game.start_time is None:
                        game.start_time = time.time()
                    
                    char_to_add = game.normalize_text(chr(ch))
                    game.typed_text += char_to_add
                    
                    # Track errors even if they'll be corrected
                    current_pos = len(game.typed_text) - 1
                    if current_pos < len(game.quote):
                        # Normalize for comparison
                        typed_normalized = game.normalize_accents(game.typed_text[current_pos])
                        quote_normalized = game.normalize_accents(game.quote[current_pos])
                        if typed_normalized != quote_normalized:
                            game.errors += 1
                    
                    should_render = True
                
                # Render on changes or WPM updates
                current_wpm = game.calculate_wpm()
                if should_render or (current_wpm != last_wpm):
                    ui.render_game_screen(game)
                    last_wpm = current_wpm
            
            # Quote completed (or shortcut was used)
            game.end_time = time.time()
            
            # This check handles the case where the shortcut was used before any typing
            if game.start_time is None:
                final_wpm = 0.0
                elapsed_time = 0.0
            else:
                final_wpm = game.calculate_wpm()
                elapsed_time = game.end_time - game.start_time

            # Calculate reward tier
            tier = game.calculate_tier(final_wpm, game.errors)
            
            # Save stats
            game.session_stats.append({
                'wpm': final_wpm,
                'time': elapsed_time,
                'tier': tier
            })
            game.save_stats(final_wpm, elapsed_time, tier)
            
            # Show completion screen with tier
            ui.render_completion_screen(game, final_wpm, elapsed_time, tier)
            
    except KeyboardInterrupt:
        ui.render_session_summary(game)


def main():
    """Main entry point"""
    try:
        curses.wrapper(main_curses)
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())