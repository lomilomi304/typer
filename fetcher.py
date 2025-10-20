#!/usr/bin/env python3
"""
Quote Extractor - Extract random quotes from books (PDF, EPUB, TXT)
with intelligent filtering and metadata tracking
"""

import sys
import random
import re
import argparse
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Set, Tuple, Optional
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass

# PDF handling
try:
    import pypdf
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

# EPUB handling
try:
    import ebooklib
    from ebooklib import epub
    from bs4 import BeautifulSoup
    HAS_EPUB = True
except ImportError:
    HAS_EPUB = False


@dataclass
class BookMetadata:
    """Store book metadata from .opf file"""
    title: str = "Unknown"
    author: str = "Unknown"
    
    def format_metadata_line(self) -> str:
        """Format metadata for quote file"""
        return f"[[BOOK: {self.title}]][[AUTHOR: {self.author}]]"


class QuoteExtractor:
    def __init__(self, min_sentences=2, max_sentences=4, skip_start_chars=50000, skip_end_chars=125000):
        self.min_sentences = min_sentences
        self.max_sentences = max_sentences
        self.skip_start_chars = skip_start_chars  # ~20 pages at 250 words/page
        self.skip_end_chars = skip_end_chars      # ~50 pages
        self.extracted_quotes = set()  # Avoid duplicates
        
    def parse_opf_metadata(self, book_dir: Path) -> BookMetadata:
        """Parse metadata.opf file to extract title and author"""
        opf_file = book_dir / "metadata.opf"
        
        if not opf_file.exists():
            return BookMetadata()
        
        try:
            tree = ET.parse(opf_file)
            root = tree.getroot()
            
            # Define namespaces
            ns = {
                'dc': 'http://purl.org/dc/elements/1.1/',
                'opf': 'http://www.idpf.org/2007/opf'
            }
            
            # Extract title
            title_elem = root.find('.//dc:title', ns)
            title = title_elem.text if title_elem is not None and title_elem.text else "Unknown"
            
            # Extract author
            author_elem = root.find('.//dc:creator', ns)
            author = author_elem.text if author_elem is not None and author_elem.text else "Unknown"
            
            return BookMetadata(title=title.strip(), author=author.strip())
            
        except Exception as e:
            print(f"Warning: Could not parse {opf_file}: {e}", file=sys.stderr)
            return BookMetadata()
    
    def extract_from_txt(self, file_path: Path) -> str:
        """Extract text from TXT file as single string"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        except Exception as e:
            print(f"Warning: Could not read {file_path}: {e}", file=sys.stderr)
            return ""
    
    def extract_from_pdf(self, file_path: Path) -> str:
        """Extract text from PDF file as single string"""
        if not HAS_PDF:
            return ""
        
        try:
            reader = pypdf.PdfReader(str(file_path))
            texts = []
            for page in reader.pages:
                text = page.extract_text()
                if text.strip():
                    texts.append(text)
            return '\n'.join(texts)
        except Exception as e:
            print(f"Warning: Could not read PDF {file_path}: {e}", file=sys.stderr)
            return ""
    
    def extract_from_epub(self, file_path: Path) -> str:
        """Extract text from EPUB file as single string"""
        if not HAS_EPUB:
            return ""
        
        try:
            book = epub.read_epub(str(file_path))
            texts = []
            
            for item in book.get_items():
                if item.get_type() == ebooklib.ITEM_DOCUMENT:
                    soup = BeautifulSoup(item.get_content(), 'html.parser')
                    text = soup.get_text()
                    if text.strip():
                        texts.append(text)
            return '\n'.join(texts)
        except Exception as e:
            print(f"Warning: Could not read EPUB {file_path}: {e}", file=sys.stderr)
            return ""
    
    def clean_text(self, text: str) -> str:
        """Clean and normalize text"""
        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text)
        # Remove page numbers at end
        text = re.sub(r'\b\d+\b\s*$', '', text)
        return text.strip()
    
    def split_into_sentences(self, text: str) -> List[str]:
        """Split text into sentences with smart handling of abbreviations"""
        # Replace common abbreviations temporarily to avoid splitting on them
        abbrev_map = {
            'Mr.': 'Mr<dot>',
            'Mrs.': 'Mrs<dot>',
            'Ms.': 'Ms<dot>',
            'Dr.': 'Dr<dot>',
            'Prof.': 'Prof<dot>',
            'Sr.': 'Sr<dot>',
            'Jr.': 'Jr<dot>',
            'vs.': 'vs<dot>',
            'etc.': 'etc<dot>',
            'i.e.': 'i<dot>e<dot>',
            'e.g.': 'e<dot>g<dot>',
            'Inc.': 'Inc<dot>',
            'Ltd.': 'Ltd<dot>',
            'Co.': 'Co<dot>',
        }
        
        # Protect abbreviations
        protected_text = text
        for abbrev, replacement in abbrev_map.items():
            protected_text = protected_text.replace(abbrev, replacement)
        
        # Split on sentence boundaries
        sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z])', protected_text)
        
        # Restore abbreviations
        restored_sentences = []
        for s in sentences:
            for abbrev, replacement in abbrev_map.items():
                s = s.replace(replacement, abbrev)
            restored_sentences.append(s)
        
        sentences = restored_sentences
        
        # Clean and filter sentences
        cleaned = []
        for s in sentences:
            s = s.strip()
            # Skip very short sentences, likely artifacts
            if len(s) < 20:
                continue
            # Skip sentences with ANY digits (footnotes, page numbers, etc.)
            if re.search(r'\d', s):
                continue
            # Skip lines that look like headers/titles (all caps, very short)
            if s.isupper() and len(s) < 50:
                continue
            cleaned.append(s)
        
        return cleaned
    
    def trim_book_content(self, text: str) -> str:
        """Remove first and last portions of the book"""
        if len(text) < (self.skip_start_chars + self.skip_end_chars):
            # Book too short, return middle portion if possible
            if len(text) > self.skip_start_chars:
                return text[self.skip_start_chars:]
            return text
        
        # Remove beginning and end
        trimmed = text[self.skip_start_chars:-self.skip_end_chars]
        return trimmed
    
    def is_valid_quote(self, quote: str) -> bool:
        """Check if quote meets quality criteria"""
        # Length check
        if len(quote) < 50 or len(quote) > 500:
            return False
        
        # Must have reasonable punctuation
        if not re.search(r'[.!?]$', quote):
            return False
        
        # Must not contain ANY digits
        if re.search(r'\d', quote):
            return False
        
        # Should not be mostly special characters
        alpha_ratio = len(re.findall(r'[a-zA-Z]', quote)) / len(quote)
        if alpha_ratio < 0.7:
            return False
        
        # Avoid quotes with too many special formatting artifacts
        if quote.count('_') > 3 or quote.count('*') > 3:
            return False
        
        # Check for duplicate
        if quote in self.extracted_quotes:
            return False
        
        return True
    
    def extract_quote_from_sentences(self, sentences: List[str]) -> Optional[str]:
        """Create a quote from a random sequence of sentences"""
        if len(sentences) < self.min_sentences:
            return None
        
        # Pick random starting point
        max_start = len(sentences) - self.min_sentences
        if max_start < 0:
            return None
        
        start_idx = random.randint(0, max_start)
        
        # Pick random length within bounds
        max_length = min(self.max_sentences, len(sentences) - start_idx)
        if max_length < self.min_sentences:
            return None
        
        num_sentences = random.randint(self.min_sentences, max_length)
        
        # Combine sentences
        quote = ' '.join(sentences[start_idx:start_idx + num_sentences])
        quote = self.clean_text(quote)
        
        return quote if self.is_valid_quote(quote) else None
    
    def extract_quotes_from_file(self, file_path: Path, metadata: BookMetadata, 
                                  num_attempts: int = 5) -> List[Tuple[str, BookMetadata]]:
        """Extract quotes from a single file with metadata"""
        # Determine file type and extract text
        suffix = file_path.suffix.lower()
        
        if suffix == '.txt':
            full_text = self.extract_from_txt(file_path)
        elif suffix == '.pdf':
            if not HAS_PDF:
                return []
            full_text = self.extract_from_pdf(file_path)
        elif suffix == '.epub':
            if not HAS_EPUB:
                return []
            full_text = self.extract_from_epub(file_path)
        else:
            return []
        
        if not full_text:
            return []
        
        # Trim beginning and end of book
        trimmed_text = self.trim_book_content(full_text)
        
        if not trimmed_text:
            return []
        
        # Split into sentences
        sentences = self.split_into_sentences(trimmed_text)
        
        if len(sentences) < self.min_sentences:
            return []
        
        # Try to extract multiple quotes from this file
        quotes = []
        attempts = 0
        max_total_attempts = num_attempts * 3  # Allow more tries to find valid quotes
        
        while len(quotes) < num_attempts and attempts < max_total_attempts:
            quote = self.extract_quote_from_sentences(sentences)
            if quote:
                self.extracted_quotes.add(quote)
                quotes.append((quote, metadata))
            attempts += 1
        
        return quotes
    
    def find_book_files(self, root_dir: Path) -> List[Path]:
        """Recursively find all supported book files"""
        extensions = ['.txt', '.pdf', '.epub']
        files = []
        
        for ext in extensions:
            files.extend(root_dir.rglob(f'*{ext}'))
        
        return files


def process_single_file(args: Tuple) -> Tuple[Path, List[Tuple[str, BookMetadata]]]:
    """Process a single file (for parallel execution)"""
    file_path, min_sentences, max_sentences, skip_start, skip_end, quotes_per_file = args
    
    # Create new extractor instance for this process
    extractor = QuoteExtractor(
        min_sentences=min_sentences,
        max_sentences=max_sentences,
        skip_start_chars=skip_start,
        skip_end_chars=skip_end
    )
    
    # Get metadata from the book's directory
    book_dir = file_path.parent
    metadata = extractor.parse_opf_metadata(book_dir)
    
    # Extract quotes
    quotes = extractor.extract_quotes_from_file(file_path, metadata, quotes_per_file)
    
    return file_path, quotes


def save_quote_immediately(quote: str, metadata: BookMetadata, output_dir: Path, counter: List[int]):
    """Save a single quote immediately with metadata"""
    output_dir.mkdir(exist_ok=True)
    
    # Increment and get current counter
    counter[0] += 1
    quote_num = counter[0]
    
    file_path = output_dir / f'quote_{quote_num}.txt'
    
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(quote + '\n')
            f.write(metadata.format_metadata_line() + '\n')
        return True
    except Exception as e:
        print(f"Error saving {file_path}: {e}", file=sys.stderr)
        return False


def get_starting_quote_number(output_dir: Path) -> int:
    """Find the next available quote number"""
    if not output_dir.exists():
        return 1
    
    existing = list(output_dir.glob('quote_*.txt'))
    if not existing:
        return 1
    
    numbers = []
    for f in existing:
        match = re.search(r'quote_(\d+)\.txt', f.name)
        if match:
            numbers.append(int(match.group(1)))
    
    return max(numbers) + 1 if numbers else 1


def main():
    parser = argparse.ArgumentParser(
        description='Extract random quotes from books with metadata',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Extract 50 quotes with 2-3 sentences each
  %(prog)s -d ~/books -n 50 -min 2 -max 3
  
  # Extract 100 quotes with 1-2 sentences each, using 8 processes
  %(prog)s -d ./library -n 100 -min 1 -max 2 -p 8
  
Supported formats: TXT, PDF, EPUB
Requirements: pip install pypdf ebooklib beautifulsoup4
        '''
    )
    
    parser.add_argument('-d', '--directory', type=Path, required=True,
                        help='Directory containing books (searches recursively)')
    parser.add_argument('-n', '--num-quotes', type=int, default=50,
                        help='Number of quotes to extract (default: 50)')
    parser.add_argument('-min', '--min-sentences', type=int, default=2,
                        help='Minimum sentences per quote (default: 2)')
    parser.add_argument('-max', '--max-sentences', type=int, default=4,
                        help='Maximum sentences per quote (default: 4)')
    parser.add_argument('-o', '--output', type=Path, default=Path('quotes'),
                        help='Output directory for quote files (default: quotes)')
    parser.add_argument('-q', '--quotes-per-file', type=int, default=5,
                        help='Max quotes to extract per book file (default: 5)')
    parser.add_argument('-p', '--processes', type=int, default=4,
                        help='Number of parallel processes (default: 4)')
    parser.add_argument('--skip-start', type=int, default=50000,
                        help='Characters to skip at start (~20 pages, default: 50000)')
    parser.add_argument('--skip-end', type=int, default=125000,
                        help='Characters to skip at end (~50 pages, default: 125000)')
    
    args = parser.parse_args()
    
    if not args.directory.exists():
        print(f"Error: Directory not found: {args.directory}", file=sys.stderr)
        return 1
    
    if args.min_sentences < 1 or args.max_sentences < args.min_sentences:
        print("Error: Invalid sentence range", file=sys.stderr)
        return 1
    
    print(f"Scanning for books in: {args.directory}")
    
    # Create a temporary extractor just to find files
    temp_extractor = QuoteExtractor()
    book_files = temp_extractor.find_book_files(args.directory)
    
    if not book_files:
        print("No book files found!")
        return 1
    
    print(f"Found {len(book_files)} book files")
    
    # Check for missing dependencies
    if not HAS_PDF:
        print("Warning: pypdf not installed. PDF files will be skipped.")
        print("Install with: pip install pypdf")
    if not HAS_EPUB:
        print("Warning: ebooklib and beautifulsoup4 not installed. EPUB files will be skipped.")
        print("Install with: pip install ebooklib beautifulsoup4")
    
    # Shuffle files for random selection
    random.shuffle(book_files)
    
    # Prepare arguments for parallel processing
    file_args = [
        (f, args.min_sentences, args.max_sentences, args.skip_start, args.skip_end, args.quotes_per_file)
        for f in book_files
    ]
    
    # Get starting quote number
    quote_counter = [get_starting_quote_number(args.output) - 1]
    total_saved = 0
    files_processed = 0
    
    print(f"\nProcessing with {args.processes} parallel processes...")
    print(f"Skipping first ~{args.skip_start} chars and last ~{args.skip_end} chars of each book")
    print(f"Filtering out any quotes containing digits\n")
    
    # Process files in parallel
    with ProcessPoolExecutor(max_workers=args.processes) as executor:
        # Submit jobs incrementally to avoid processing too many files
        future_to_file = {}
        file_iter = iter(file_args)
        
        # Submit initial batch
        for _ in range(min(args.processes * 2, len(file_args))):
            try:
                arg = next(file_iter)
                future = executor.submit(process_single_file, arg)
                future_to_file[future] = arg[0]
            except StopIteration:
                break
        
        # Process results as they complete
        for future in as_completed(future_to_file):
            if total_saved >= args.num_quotes:
                # Cancel any remaining futures
                for f in future_to_file:
                    if not f.done():
                        f.cancel()
                break
            
            file_path = future_to_file[future]
            
            try:
                _, quotes_with_metadata = future.result()
                
                if quotes_with_metadata:
                    print(f"Processing: {file_path.name}... ", end='')
                    
                    saved_from_file = 0
                    for quote, metadata in quotes_with_metadata:
                        if total_saved >= args.num_quotes:
                            break
                        
                        if save_quote_immediately(quote, metadata, args.output, quote_counter):
                            total_saved += 1
                            saved_from_file += 1
                    
                    print(f"✓ ({saved_from_file} quotes saved)")
                    files_processed += 1
                else:
                    print(f"Processing: {file_path.name}... ✗")
                
                # Submit next job if we need more quotes and have more files
                if total_saved < args.num_quotes:
                    try:
                        arg = next(file_iter)
                        new_future = executor.submit(process_single_file, arg)
                        future_to_file[new_future] = arg[0]
                    except StopIteration:
                        pass
                    
            except Exception as e:
                print(f"Error processing {file_path.name}: {e}", file=sys.stderr)
    
    print(f"\nExtracted and saved {total_saved} quotes from {files_processed} books")
    print(f"Quotes saved to: {args.output}")
    
    if total_saved > 0:
        return 0
    else:
        print("No quotes extracted!", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())