import io
import re
import base64
import requests
from datetime import datetime
from typing import Optional
from flask import Response
import markdown
from bs4 import BeautifulSoup
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
import textwrap

# Try to import weasyprint, fallback to xhtml2pdf if not available
HAS_WEASYPRINT = False
HAS_XHTML2PDF = False

try:
    from weasyprint import HTML as WeasyHTML
    HAS_WEASYPRINT = True
except (ImportError, OSError):
    pass

# Try xhtml2pdf as fallback if weasyprint is not available
if not HAS_WEASYPRINT:
    try:
        from xhtml2pdf import pisa
        HAS_XHTML2PDF = True
    except ImportError:
        pass


def parse_message_content(content: str):
    """
    Parse message content to extract HTML tables, images, and markdown text.
    Returns a dict with 'tables', 'images', and 'text' keys.
    """
    result = {
        'tables': [],
        'images': [],
        'text': content
    }

    # Extract HTML tables and images
    soup = BeautifulSoup(content, 'html.parser')
    tables = soup.find_all('table')
    images = soup.find_all('img')

    if tables:
        # Remove tables from text for cleaner markdown processing
        for table in tables:
            table_str = str(table)
            result['tables'].append(table_str)
            # Replace table with placeholder in text
            result['text'] = result['text'].replace(table_str, f"[TABLE_{len(result['tables']) - 1}]", 1)
            # Also remove from soup to ensure it's completely removed
            table.decompose()

    if images:
        # Extract and process images
        for img in images:
            img_src = img.get('src', '')
            img_alt = img.get('alt', '')
            img_str = str(img)
            result['images'].append({
                'html': img_str,
                'src': img_src,
                'alt': img_alt
            })
            # Replace image with placeholder in text
            result['text'] = result['text'].replace(img_str, f"[IMAGE_{len(result['images']) - 1}]", 1)
            # Also remove from soup
            img.decompose()

    return result


def fetch_image_as_data_url(url: str) -> Optional[str]:
    """
    Fetch an image from URL and convert to data URL.
    Returns None if image cannot be fetched.
    """
    try:
        response = requests.get(url, timeout=10, stream=True)
        response.raise_for_status()

        # Check if it's an image
        content_type = response.headers.get('content-type', '')
        if not content_type.startswith('image/'):
            return None

        # Read image data
        image_data = response.content

        # Convert to base64 data URL
        base64_data = base64.b64encode(image_data).decode('utf-8')
        return f"data:{content_type};base64,{base64_data}"
    except Exception:
        return None


def process_images_in_html(html_content: str, images: list) -> str:
    """
    Process images in HTML content, converting URLs to data URLs where possible.
    Handles both HTML img tags and markdown image syntax.
    """
    soup = BeautifulSoup(html_content, 'html.parser')

    # Find all img tags
    for img in soup.find_all('img'):
        src = img.get('src', '')
        if src:
            # If it's already a data URL, keep it
            if src.startswith('data:'):
                continue

            # If it's a URL, try to fetch and convert
            if src.startswith('http://') or src.startswith('https://'):
                data_url = fetch_image_as_data_url(src)
                if data_url:
                    img['src'] = data_url
                else:
                    # If fetch fails, keep original URL (weasyprint may handle it)
                    pass
            # If it's a relative path or local file, keep as is
            # (weasyprint will try to resolve it)

    return str(soup)


def find_optimal_break_point(text: str, max_length: int) -> int:
    """
    Find the best break point in text for wrapping.
    Prioritizes: spaces > special chars > numeric boundaries > character boundaries
    """
    if len(text) <= max_length:
        return len(text)
    
    # Priority 1: Break at spaces (word boundaries)
    for i in range(max_length, max(0, max_length - 10), -1):
        if i < len(text) and text[i] == ' ':
            return i + 1  # Break after space
    
    # Priority 2: Break at special characters (colons, hyphens, slashes, etc.)
    special_chars = [':', '-', '/', '_', '.', ',', ';']
    for i in range(max_length, max(0, max_length - 10), -1):
        if i < len(text) and text[i] in special_chars:
            return i + 1  # Break after special char
    
    # Priority 3: Break at numeric boundaries (transition between number and non-number)
    for i in range(max_length, max(0, max_length - 10), -1):
        if i > 0 and i < len(text):
            # Break between number and letter, or letter and number
            is_digit_before = text[i-1].isdigit()
            is_digit_after = text[i].isdigit() if i < len(text) else False
            if is_digit_before != is_digit_after:
                return i
    
    # Priority 4: Break after vowels (more natural word breaks)
    vowels = 'aeiouAEIOU'
    for i in range(max_length, max(0, max_length - 5), -1):
        if i > 0 and i < len(text) and text[i-1] in vowels:
            return i
    
    # Priority 5: Break at max_length (hard break)
    return max_length


def hyphenate_long_word(word: str, max_length: int = 15) -> str:
    """
    Intelligently split long words with hyphens when they exceed max_length.
    Tries to break at natural points: spaces, special chars, numeric boundaries, vowels.
    """
    if len(word) <= max_length:
        return word
    
    # Check for common separators first (colons, slashes)
    if ':' in word:
        parts = word.split(':', 1)
        if len(parts[0]) <= max_length:
            return f"{parts[0]}:<br/>{parts[1]}"
    
    if '/' in word:
        parts = word.split('/', 1)
        if len(parts[0]) <= max_length:
            return f"{parts[0]}/<br/>{parts[1]}"
    
    # Find optimal break point
    break_point = find_optimal_break_point(word, max_length)
    
    # Ensure we don't break at the very start or end
    if break_point <= 2:
        break_point = max_length
    if break_point >= len(word) - 2:
        break_point = len(word) - 2
    
    return f"{word[:break_point]}-<br/>{word[break_point:]}"


def wrap_text_with_hyphenation(text: str, max_width: int = 20) -> str:
    """
    Wrap text intelligently, breaking long words with hyphens when needed.
    """
    if not text:
        return text
    
    words = text.split()
    result = []
    current_line = []
    current_length = 0
    
    for word in words:
        # Check if word needs hyphenation
        if len(word) > max_width:
            # Hyphenate the word
            hyphenated = hyphenate_long_word(word, max_width)
            # If hyphenation added <br/>, it's already split
            if '<br/>' in hyphenated:
                # Add current line if it has content
                if current_line:
                    result.append(' '.join(current_line))
                    current_line = []
                result.append(hyphenated.replace('<br/>', '\n'))
                current_length = 0
            else:
                # Word was shortened but not split, add it
                if current_length + len(hyphenated) + 1 > max_width and current_line:
                    result.append(' '.join(current_line))
                    current_line = [hyphenated]
                    current_length = len(hyphenated)
                else:
                    current_line.append(hyphenated)
                    current_length += len(hyphenated) + 1
        else:
            # Regular word
            if current_length + len(word) + 1 > max_width and current_line:
                result.append(' '.join(current_line))
                current_line = [word]
                current_length = len(word)
            else:
                current_line.append(word)
                current_length += len(word) + 1
    
    if current_line:
        result.append(' '.join(current_line))
    
    return '\n'.join(result)


def process_table_headers(soup: BeautifulSoup) -> BeautifulSoup:
    """
    Process table headers to split long headers into multiple lines.
    Specifically handles headers like "Interest/Dividend" to split properly.
    """
    tables = soup.find_all('table')
    
    for table in tables:
        # Find all header cells
        header_cells = table.find_all(['th'])
        if not header_cells:
            # Try thead > th or first row th/td
            thead = table.find('thead')
            if thead:
                header_cells = thead.find_all(['th', 'td'])
            else:
                first_row = table.find('tr')
                if first_row:
                    header_cells = first_row.find_all(['th', 'td'])
        
        for cell in header_cells:
            text = cell.get_text(strip=True)
            if not text:
                continue
            
            # Clear existing content
            cell.clear()
            
            # Split headers with "/" into multiple lines (e.g., "Interest/Dividends" -> "Interest / Dividends")
            # Also handle "Interest/Dividend" (singular)
            if '/' in text:
                # Normalize text first (remove extra spaces)
                text = ' '.join(text.split())
                parts = text.split('/')
                if len(parts) == 2:
                    # Create a line break between parts with space before slash
                    # Format: "Interest /" on first line, "Dividends" on second line
                    first_part = parts[0].strip()
                    second_part = parts[1].strip()
                    
                    # Add first part with space and slash
                    cell.append(first_part)
                    cell.append(' /')  # Add space before slash on first line
                    # Add line break
                    br = soup.new_tag('br')
                    cell.append(br)
                    # Add second part on new line
                    cell.append(second_part)
                else:
                    # Multiple slashes, split at first one
                    first_part = parts[0].strip()
                    rest = '/'.join(parts[1:]).strip()
                    cell.append(first_part)
                    cell.append(' /')  # Add space before slash
                    br = soup.new_tag('br')
                    cell.append(br)
                    cell.append(rest)
            
            # For headers with colons (e.g., "Citi Private:Singapore"), split at colon
            elif ':' in text and len(text) > 15:
                parts = text.split(':', 1)
                if len(parts) == 2:
                    cell.append(parts[0] + ':')
                    br = soup.new_tag('br')
                    cell.append(br)
                    cell.append(parts[1])
                else:
                    # No colon split possible, try other methods
                    cell.append(text)
            
            # For other long headers, try to split at natural break points
            elif len(text) > 15:
                # Try to split at spaces or special characters
                if ' ' in text:
                    # Split at middle space if possible
                    words = text.split()
                    if len(words) >= 2:
                        mid = len(words) // 2
                        first_half = ' '.join(words[:mid])
                        second_half = ' '.join(words[mid:])
                        cell.append(first_half)
                        br = soup.new_tag('br')
                        cell.append(br)
                        cell.append(second_half)
                    else:
                        # Single long word, keep as is (will be handled by CSS)
                        cell.append(text)
                else:
                    # Single long word without spaces, keep as is
                    cell.append(text)
            else:
                # Short header, no splitting needed
                cell.append(text)
    
    return soup


def process_table_cells_for_wrapping(soup: BeautifulSoup) -> BeautifulSoup:
    """
    Process table cells to handle text overflow with proper wrapping and hyphenation.
    Intelligently breaks long words at: spaces, special chars, numeric boundaries, vowels.
    Handles cases like "Citi Private:Singapore" by splitting at colons when appropriate.
    """
    tables = soup.find_all('table')
    
    for table in tables:
        # Process all cells (both th and td)
        cells = table.find_all(['th', 'td'])
        
        for cell in cells:
            text = cell.get_text(strip=True)
            if not text:
                continue
            
            # Check if text contains long words or needs wrapping
            words = text.split()
            has_long_words = any(len(word) > 15 for word in words)
            is_long_text = len(text) > 20
            
            # For cells with long content, add wrapping attributes
            if is_long_text or has_long_words:
                # Add style for word breaking
                existing_style = cell.get('style', '')
                style_parts = []
                if existing_style:
                    style_parts.append(existing_style.rstrip(';'))
                
                # Add word breaking styles
                style_parts.append('word-wrap: break-word')
                style_parts.append('overflow-wrap: break-word')
                style_parts.append('word-break: break-word')
                style_parts.append('white-space: normal')
                
                cell['style'] = '; '.join(style_parts) + ';'
                
                # For text with colons (like "Citi Private:Singapore"), add line break opportunity
                if ':' in text and len(text) > 20:
                    # Don't modify if it's already been processed as a header
                    if cell.name != 'th' or not any(br for br in cell.find_all('br')):
                        # Check if splitting at colon would help
                        parts = text.split(':', 1)
                        if len(parts) == 2 and len(parts[0]) < 20:
                            # Clear and rebuild with line break
                            cell.clear()
                            cell.append(parts[0] + ':')
                            br = soup.new_tag('br')
                            cell.append(br)
                            cell.append(parts[1])
                            continue
                
                # For very long words without spaces, break them intelligently
                if has_long_words and cell.string == text:  # Only if not already modified
                    new_words = []
                    for word in words:
                        if len(word) > 15:
                            # Use intelligent break point finding
                            # Try to break at optimal points
                            break_point = find_optimal_break_point(word, 15)
                            
                            if break_point < len(word):
                                # Break the word
                                first_part = word[:break_point]
                                second_part = word[break_point:]
                                
                                # Add soft hyphen or zero-width space for better breaking
                                # Use zero-width space for better browser support
                                new_words.append(f"{first_part}\u200B{second_part}")
                            else:
                                new_words.append(word)
                        else:
                            new_words.append(word)
                    
                    # Update cell text with intelligent breaks
                    if cell.string == text:
                        cell.string = ' '.join(new_words)
    
    return soup


def calculate_responsive_column_widths(table_soup) -> dict:
    """
    Calculate intelligent responsive column widths based on content analysis.
    - Short/repetitive content (like "0", "Fixed Income") gets minimal width
    - Headers are ensured to be fully visible
    - Long content gets appropriate width with min/max constraints
    - Considers multi-line content and wrapped text
    Returns a dict mapping column index to width percentage.
    """
    # Find the table element if we got a soup object
    if isinstance(table_soup, BeautifulSoup):
        table = table_soup.find('table')
    else:
        table = table_soup
    
    if not table:
        return {}
    
    # Find all rows to analyze content
    rows = table.find_all('tr')
    if not rows:
        return {}
    
    # Get number of columns from first row
    first_row_cells = rows[0].find_all(['th', 'td'])
    num_cols = len(first_row_cells)
    if num_cols == 0:
        return {}
    
    # Separate header row from data rows
    header_row = None
    data_rows = []
    
    thead = table.find('thead')
    if thead:
        header_row = thead.find('tr')
        data_rows = rows
    else:
        # First row might be headers
        if rows:
            header_row = rows[0]
            data_rows = rows[1:] if len(rows) > 1 else []
    
    # Analyze headers first (must be fully visible)
    header_lengths = [0] * num_cols
    if header_row:
        header_cells = header_row.find_all(['th', 'td'])
        for idx, cell in enumerate(header_cells[:num_cols]):
            # Get text, accounting for line breaks (split headers)
            # For split headers like "Interest / Dividends", use the longest line
            cell_html = str(cell)
            if '<br' in cell_html or '<br/>' in cell_html:
                # Header is split - extract text parts separated by <br>
                # Get text with line breaks preserved
                text_with_breaks = cell.get_text(separator='\n', strip=True)
                # Split by line breaks and find longest line
                lines = [line.strip() for line in text_with_breaks.split('\n') if line.strip()]
                if lines:
                    text = max(lines, key=len)
                else:
                    text = cell.get_text(separator=' ', strip=True)
            else:
                text = cell.get_text(separator=' ', strip=True)
                # For headers with line breaks in text, use the longest line
                if '\n' in text:
                    lines = [line.strip() for line in text.split('\n') if line.strip()]
                    text = max(lines, key=len) if lines else text
            header_lengths[idx] = len(text)
    
    # Analyze data content
    max_data_lengths = [0] * num_cols
    min_data_lengths = [float('inf')] * num_cols
    content_types = ['mixed'] * num_cols  # 'short', 'repetitive', 'long', 'mixed'
    all_values_per_col = [[] for _ in range(num_cols)]
    
    for row in data_rows:
        cells = row.find_all(['th', 'td'])
        for idx, cell in enumerate(cells[:num_cols]):
            text = cell.get_text(strip=True)
            if not text:
                continue
            
            # Check for multi-line content (wrapped text)
            has_line_breaks = '\n' in text or '<br' in str(cell)
            if has_line_breaks:
                # For wrapped content, use the longest line (actual width needed)
                lines = re.split(r'[\n<br/>]+', text)
                text = max(lines, key=len) if lines else text
            
            # Calculate effective length
            length = len(text)
            
            # Adjust for numbers/currency (typically narrower in display)
            if re.match(r'^[\$,\d\.\-\s%]+$', text):
                length = int(length * 0.75)  # Numbers take less space
            
            max_data_lengths[idx] = max(max_data_lengths[idx], length)
            min_data_lengths[idx] = min(min_data_lengths[idx], length)
            all_values_per_col[idx].append(text)
    
    # Determine content characteristics per column
    for idx in range(num_cols):
        values = all_values_per_col[idx]
        if not values:
            continue
        
        # Check if all values are the same (repetitive)
        unique_values = set(values)
        if len(unique_values) == 1:
            content_types[idx] = 'repetitive'
        # Check if all values are very short
        elif max_data_lengths[idx] <= 5:
            content_types[idx] = 'short'
        # Check if values are consistently long
        elif min_data_lengths[idx] > 20:
            content_types[idx] = 'long'
        else:
            content_types[idx] = 'mixed'
    
    # Calculate required width per column (actual used width only - NO minimum width)
    # Use max of header length and data length - use exact content width
    required_lengths = []
    
    for idx in range(num_cols):
        # Header must be fully visible
        header_len = header_lengths[idx]
        data_len = max_data_lengths[idx] if max_data_lengths[idx] > 0 else 0
        
        # Actual required length: max of header and data (no minimum constraint)
        actual_required = max(header_len, data_len)
        
        # Add small padding (1-2 chars) for readability, but no minimum width
        if actual_required > 0:
            actual_required += 1  # Just 1 char padding
        else:
            actual_required = 2  # Absolute minimum for empty columns
        
        required_lengths.append(actual_required)
    
    # Use actual required lengths directly - no minimum width constraints
    optimized_lengths = required_lengths.copy()
    
    # Calculate total optimized length
    total_length = sum(optimized_lengths)
    if total_length == 0:
        # Fallback: equal distribution
        return {idx: 100 / num_cols for idx in range(num_cols)}
    
    # Calculate percentages based on optimized lengths
    widths = {}
    for idx in range(num_cols):
        opt_length = optimized_lengths[idx]
        
        if total_length > 0:
            # Base percentage from optimized length
            percentage = (opt_length / total_length) * 100
        else:
            percentage = 100 / num_cols
        
        widths[idx] = percentage
    
    # Normalize to ensure total is exactly 100%
    total_percentage = sum(widths.values())
    if total_percentage > 0 and abs(total_percentage - 100) > 0.01:
        # Scale all percentages proportionally
        scale_factor = 100 / total_percentage
        for idx in widths:
            widths[idx] *= scale_factor
    
    return widths


def generate_pdf_from_message(message: dict) -> bytes:
    """
    Generate PDF from message content.
    Handles HTML tables, images, markdown formatting, lists, and text styles.
    """
    content = message.get('content', '')
    role = message.get('role', 'assistant')
    created_at = message.get('created_at', datetime.now().timestamp())

    # Parse content (extracts HTML tables only)
    parsed = parse_message_content(content)

    # Convert markdown to HTML with extensions FIRST to catch markdown tables
    # Use standard extensions that are commonly available
    extensions_list = ['tables', 'fenced_code', 'nl2br']

    # Try to add extra extensions if available
    try:
        import markdown.extensions.extra
        extensions_list.append('extra')
    except:
        pass

    try:
        import markdown.extensions.codehilite
        extensions_list.append('codehilite')
    except:
        pass

    try:
        import markdown.extensions.sane_lists
        extensions_list.append('sane_lists')
    except:
        pass

    # Convert markdown to HTML - this converts markdown tables to HTML tables
    markdown_html = markdown.markdown(
        parsed['text'],
        extensions=extensions_list
    )
    
    # Parse the markdown HTML to work with it
    html_soup = BeautifulSoup(markdown_html, 'html.parser')
    
    # Find all tables in the converted HTML (includes markdown tables)
    all_tables_in_html = html_soup.find_all('table')
    
    # Combine pre-extracted HTML tables and markdown-converted tables for detection
    all_tables_html = []
    if parsed['tables']:
        all_tables_html.extend(parsed['tables'])
    # Add markdown tables as HTML strings
    for table in all_tables_in_html:
        all_tables_html.append(str(table))
    
    # Re-insert pre-extracted HTML tables into html_content
    html_content = str(html_soup)
    for i, table_html in enumerate(parsed['tables']):
        placeholder = f"[TABLE_{i}]"
        if placeholder in html_content:
            html_content = html_content.replace(placeholder, table_html, 1)

    # Detect table dimensions from all tables (both HTML and markdown-converted)
    use_landscape = False
    use_a3 = False
    reduce_font_size = False
    max_columns = 0
    max_rows = 0
    
    # Function to count columns and rows in a table
    def count_table_dimensions(table):
        """Count columns and rows in a table element."""
        num_columns = 0
        num_rows = 0
        
        if not table:
            return 0, 0
        
        # Count columns - be thorough and check all rows to find maximum
        all_rows = table.find_all('tr')
        max_cells = 0
        
        # Check header first
        header_row = table.find('thead')
        if header_row:
            header_cells = header_row.find_all(['th', 'td'])
            max_cells = max(max_cells, len(header_cells))
        
        # Check all rows to find the maximum number of cells
        for row in all_rows:
            cells = row.find_all(['th', 'td'])
            max_cells = max(max_cells, len(cells))
        
        num_columns = max_cells
        
        # Count rows (excluding header if it's in thead)
        tbody = table.find('tbody')
        if tbody:
            rows = tbody.find_all('tr')
        else:
            # All rows, but skip header row if it's not in thead
            if header_row:
                rows = all_rows
            else:
                # First row might be header, count from second row
                rows = all_rows[1:] if len(all_rows) > 1 else []
        
        num_rows = len(rows)
        return num_columns, num_rows
    
    # Check all tables (both pre-extracted HTML and markdown-converted)
    # Use all_tables_html which contains both HTML tables and markdown-converted tables
    if all_tables_html:
        for table_html in all_tables_html:
            soup_table = BeautifulSoup(table_html, 'html.parser')
            table = soup_table.find('table')
            if table:
                num_columns, num_rows = count_table_dimensions(table)
                max_columns = max(max_columns, num_columns)
                max_rows = max(max_rows, num_rows)
    
    # Debug: Verify column count
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"PDF Generation: Detected max_columns={max_columns}, max_rows={max_rows}")
    
    # Apply decisions based on maximum columns found
    # Priority order:
    # 1. 10+ columns (>= 10) → A3 portrait (widest option)
    # 2. 7-9 columns (>= 7 and < 10) → A4 landscape
    # 3. 5-6 columns (>= 5 and < 7) → A4 portrait
    # 4. Otherwise (< 5 columns) → A4 portrait
    # Note: Row count is NOT used to avoid conflicts with column-based decisions
    
    # Reset flags first
    use_a3 = False
    use_landscape = False
    
    # Check for 10+ columns FIRST (A3 portrait)
    # This means 10, 11, 12, 13+ columns should use A3 portrait
    if max_columns >= 10:
        use_a3 = True
        use_landscape = False  # A3 portrait, not landscape
        logger.info(f"PDF: Using A3 portrait for {max_columns} columns (>= 10)")
    # Check for 7-9 columns (A4 landscape)
    # This means 7, 8, 9 columns should use A4 landscape
    elif max_columns >= 7:
        use_a3 = False
        use_landscape = True
        logger.info(f"PDF: Using A4 landscape for {max_columns} columns (7-9 range)")
    # Check for 5-6 columns (A4 portrait)
    # This means 5, 6 columns should use A4 portrait
    elif max_columns >= 5:
        use_a3 = False
        use_landscape = False
        logger.info(f"PDF: Using A4 portrait for {max_columns} columns (5-6 range)")
    # Otherwise A4 portrait (less than 5 columns)
    else:
        use_a3 = False
        use_landscape = False
        logger.info(f"PDF: Using A4 portrait for {max_columns} columns (< 5)")
    
    # Reduce font size for very large tables (8+ columns OR 15+ rows)
    if max_columns >= 8 or max_rows >= 15:
        reduce_font_size = True

    # Process all tables in the HTML content (both pre-extracted and markdown-converted)
    # Parse the HTML content and process tables in place
    final_soup = BeautifulSoup(html_content, 'html.parser')
    all_tables = final_soup.find_all('table')
    
    for table in all_tables:
        # Ensure table has proper structure (thead/tbody)
        # Markdown tables might not have thead/tbody, so we need to add them
        if not table.find('thead') and not table.find('tbody'):
            # First row is likely header
            first_row = table.find('tr')
            if first_row:
                # Check if first row has th tags (header)
                if first_row.find('th'):
                    thead = final_soup.new_tag('thead')
                    thead.append(first_row.extract())
                    table.insert(0, thead)
                    
                    # Remaining rows go in tbody
                    remaining_rows = table.find_all('tr')
                    if remaining_rows:
                        tbody = final_soup.new_tag('tbody')
                        for row in remaining_rows:
                            tbody.append(row.extract())
                        table.append(tbody)
        
        # Process table for header splitting and cell wrapping
        table_soup = BeautifulSoup(str(table), 'html.parser')
        table_elem = table_soup.find('table')
        if table_elem:
            table_soup = process_table_headers(table_soup)
            table_soup = process_table_cells_for_wrapping(table_soup)
            
            # Calculate and apply responsive column widths
            processed_table = table_soup.find('table')
            if processed_table:
                widths = calculate_responsive_column_widths(table_soup)
                if widths:
                    # Create column group for responsive widths
                    first_row = processed_table.find('tr')
                    if first_row:
                        num_cols = len(first_row.find_all(['th', 'td']))
                    else:
                        num_cols = len(widths)
                    
                    colgroup = table_soup.new_tag('colgroup')
                    for idx in range(num_cols):
                        col = table_soup.new_tag('col')
                        width_pct = widths.get(idx, 100 / num_cols)
                        col['style'] = f'width: {width_pct}%;'
                        colgroup.append(col)
                    
                    # Insert colgroup if not already present
                    if processed_table.find('colgroup') is None:
                        first_child = next(processed_table.children, None)
                        if first_child:
                            processed_table.insert(0, colgroup)
                        else:
                            processed_table.append(colgroup)
                
                # Replace the original table with processed version
                table.replace_with(processed_table)
    
    html_content = str(final_soup)

    # Process images in the HTML content (both HTML img tags and markdown images)
    html_content = process_images_in_html(html_content, parsed['images'])

    # Re-insert any images that were extracted as placeholders
    for i, image_info in enumerate(parsed['images']):
        placeholder = f"[IMAGE_{i}]"
        if placeholder in html_content:
            # Process image URL to data URL if possible
            img_html = image_info['html']
            processed_img = process_images_in_html(img_html, [image_info])
            html_content = html_content.replace(placeholder, processed_img)

    # Set page size and orientation based on table detection
    # Use explicit dimensions for better compatibility with both weasyprint and xhtml2pdf
    if use_a3:
        if use_landscape:
            # A3 landscape: 420mm x 297mm (width x height)
            # For landscape, width > height
            page_size_css = "420mm 297mm"
            page_size_named = "A3 landscape"
        else:
            # A3 portrait: 297mm x 420mm (width x height)
            # For portrait, height > width
            page_size_css = "297mm 420mm"
            page_size_named = "A3"
        page_margin = "1cm"  # Smaller margin for A3 to maximize space
    elif use_landscape:
        # A4 landscape: 297mm x 210mm (width x height)
        # For landscape, width > height
        page_size_css = "297mm 210mm"
        page_size_named = "A4 landscape"
        page_margin = "1.5cm"  # Smaller margin for landscape
    else:
        # A4 portrait: 210mm x 297mm (width x height)
        # For portrait, height > width
        page_size_css = "210mm 297mm"
        page_size_named = "A4"
        page_margin = "2cm"
    
    # Set font size based on table size
    table_font_size = "6pt" if reduce_font_size else "8pt"

    html_document = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            @page {{
                size: {page_size_css};
                margin: {page_margin};
            }}
            @page {{
                size: {page_size_named};
                margin: {page_margin};
            }}
            /* Force landscape orientation for A3 */
            @page {{
                size: {page_size_css};
                margin: {page_margin};
            }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                font-size: 12pt;
                line-height: 1.6;
                color: #333;
                background: #fff;
            }}
            .content {{
                margin-top: 15px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin: 10px 0;
                font-size: {table_font_size};
                table-layout: fixed;
                page-break-inside: auto;
            }}
            table thead {{
                display: table-header-group;
            }}
            table tbody {{
                display: table-row-group;
            }}
            table tfoot {{
                display: table-footer-group;
            }}
            table colgroup col {{
                width: auto;
            }}
            table th {{
                background-color: #f5f5f5;
                border: 1px solid #ddd;
                padding: 2px 3px;
                text-align: left;
                font-weight: bold;
                font-size: {table_font_size};
                word-wrap: break-word;
                overflow-wrap: break-word;
                word-break: break-word;
                white-space: normal;
                hyphens: auto;
                line-height: 1.2;
                overflow: hidden;
            }}
            table td {{
                border: 1px solid #ddd;
                padding: 2px 3px;
                font-size: {table_font_size};
                word-wrap: break-word;
                overflow-wrap: break-word;
                word-break: break-word;
                white-space: normal;
                hyphens: auto;
                line-height: 1.2;
                overflow: hidden;
            }}
            table tr {{
                line-height: 1.1;
                page-break-inside: avoid;
                page-break-after: auto;
            }}
            /* Prevent table rows from breaking across pages */
            table tbody tr {{
                page-break-inside: avoid;
            }}
            /* Keep table header on each page */
            table thead {{
                display: table-header-group;
            }}
            table tr:nth-child(even) {{
                background-color: #f9f9f9;
            }}
            h1, h2, h3, h4, h5, h6 {{
                margin-top: 20px;
                margin-bottom: 10px;
                color: #333;
                page-break-after: avoid;
            }}
            h1 {{ font-size: 18pt; font-weight: bold; }}
            h2 {{ font-size: 16pt; font-weight: bold; }}
            h3 {{ font-size: 14pt; font-weight: bold; }}
            h4 {{ font-size: 12pt; font-weight: bold; }}
            h5 {{ font-size: 11pt; font-weight: bold; }}
            h6 {{ font-size: 10pt; font-weight: bold; }}
            
            /* Multi-level lists */
            ul, ol {{
                margin: 10px 0;
                padding-left: 30px;
            }}
            ul ul, ol ol, ul ol, ol ul {{
                margin: 5px 0;
                padding-left: 25px;
            }}
            li {{
                margin: 5px 0;
                line-height: 1.5;
            }}
            li > ul, li > ol {{
                margin-top: 5px;
                margin-bottom: 5px;
            }}
            
            /* Nested list styling */
            ul {{
                list-style-type: disc;
            }}
            ul ul {{
                list-style-type: circle;
            }}
            ul ul ul {{
                list-style-type: square;
            }}
            ol {{
                list-style-type: decimal;
            }}
            ol ol {{
                list-style-type: lower-alpha;
            }}
            ol ol ol {{
                list-style-type: lower-roman;
            }}
            
            /* Images */
            img {{
                max-width: 100%;
                height: auto;
                margin: 15px 0;
                page-break-inside: avoid;
                display: block;
            }}
            img[src^="data:"] {{
                max-width: 100%;
            }}
            
            /* Text styles */
            p {{
                margin: 10px 0;
                line-height: 1.6;
            }}
            code {{
                background-color: #f4f4f4;
                padding: 2px 4px;
                border-radius: 3px;
                font-family: 'Courier New', monospace;
                font-size: 10pt;
            }}
            pre {{
                background-color: #f4f4f4;
                padding: 10px;
                border-radius: 5px;
                overflow-x: auto;
            }}
            strong, b {{
                font-weight: bold;
            }}
            em, i {{
                font-style: italic;
            }}
            u {{
                text-decoration: underline;
            }}
            s, strike, del {{
                text-decoration: line-through;
            }}
            sup {{
                vertical-align: super;
                font-size: 0.8em;
            }}
            sub {{
                vertical-align: sub;
                font-size: 0.8em;
            }}
            mark {{
                background-color: #ffeb3b;
                padding: 2px 4px;
            }}
            small {{
                font-size: 0.9em;
            }}
            blockquote {{
                border-left: 4px solid #ddd;
                margin: 15px 0;
                padding-left: 15px;
                color: #666;
                font-style: italic;
            }}
            a {{
                color: #0066cc;
                text-decoration: underline;
            }}
            a:hover {{
                color: #0052a3;
            }}
            hr {{
                border: none;
                border-top: 1px solid #ddd;
                margin: 20px 0;
            }}
        </style>
    </head>
    <body>
        <div class="content">
            {html_content}
        </div>
    </body>
    </html>
    """

    # Generate PDF using available library
    if HAS_WEASYPRINT:
        # WeasyPrint supports CSS @page size directly
        # Create HTML object and write PDF - it will respect @page CSS rules
        try:
            html_obj = WeasyHTML(string=html_document)
            pdf_bytes = html_obj.write_pdf()
        except Exception as e:
            # Fallback: try with explicit page size
            import logging
            logging.getLogger(__name__).warning(f"WeasyPrint error: {e}, trying fallback")
            html_obj = WeasyHTML(string=html_document)
            pdf_bytes = html_obj.write_pdf()
    elif HAS_XHTML2PDF:
        # xhtml2pdf uses CSS @page for page size
        # The @page CSS rules should be respected
        pdf_buffer = io.BytesIO()
        try:
            pisa.CreatePDF(io.StringIO(html_document), dest=pdf_buffer)
        except Exception as e:
            # Fallback if there's an error
            import logging
            logging.getLogger(__name__).warning(f"xhtml2pdf error: {e}")
            pdf_buffer = io.BytesIO()
            pisa.CreatePDF(io.StringIO(html_document), dest=pdf_buffer)
        pdf_bytes = pdf_buffer.getvalue()
        pdf_buffer.close()
    else:
        raise RuntimeError(
            "No PDF generation library available. Please install weasyprint or xhtml2pdf. "
            "On Windows, weasyprint requires GTK+ libraries. "
            "Consider using xhtml2pdf as an alternative."
        )
    return pdf_bytes


def generate_excel_from_message(message: dict) -> bytes:
    """
    Generate Excel file from message content.
    Handles HTML tables, markdown formatting, and text content.
    """
    content = message.get('content', '')
    role = message.get('role', 'assistant')
    created_at = message.get('created_at', datetime.now().timestamp())

    # Parse content
    parsed = parse_message_content(content)

    # Convert markdown to HTML to catch markdown tables
    extensions_list = ['tables', 'fenced_code', 'nl2br']
    try:
        import markdown.extensions.extra
        extensions_list.append('extra')
    except:
        pass
    try:
        import markdown.extensions.codehilite
        extensions_list.append('codehilite')
    except:
        pass
    try:
        import markdown.extensions.sane_lists
        extensions_list.append('sane_lists')
    except:
        pass
    
    markdown_html = markdown.markdown(parsed['text'], extensions=extensions_list)
    markdown_soup = BeautifulSoup(markdown_html, 'html.parser')
    markdown_tables = markdown_soup.find_all('table')
    
    # Combine pre-extracted HTML tables and markdown-converted tables
    all_tables = []
    if parsed['tables']:
        all_tables.extend(parsed['tables'])
    # Add markdown tables as HTML strings
    for table in markdown_tables:
        all_tables.append(str(table))

    # Create workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Message Content"

    # Header row styling
    header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=12)
    border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )

    # First, extract all table data to identify what should be removed from text
    table_data_values = set()
    table_header_names = set()
    if all_tables:
        for table_html in all_tables:
            soup_table = BeautifulSoup(table_html, 'html.parser')
            table = soup_table.find('table')
            if table:
                # Extract headers first
                header_row = table.find('thead')
                if header_row:
                    header_cells = header_row.find_all(['th', 'td'])
                    for cell in header_cells:
                        header_text = cell.get_text(strip=True)
                        if header_text:
                            table_header_names.add(header_text)
                else:
                    # Try first row as headers
                    first_row = table.find('tr')
                    if first_row:
                        header_cells = first_row.find_all(['th', 'td'])
                        for cell in header_cells:
                            header_text = cell.get_text(strip=True)
                            if header_text:
                                table_header_names.add(header_text)
                
                # Extract all cell values from the table
                for row in table.find_all('tr'):
                    for cell in row.find_all(['td', 'th']):
                        cell_text = cell.get_text(strip=True)
                        if cell_text:
                            table_data_values.add(cell_text)
    
    # Convert markdown to plain text (remove markdown syntax)
    text_content = parsed['text']
    
    # Remove table and image placeholders first (they will be rendered separately as Excel tables)
    text_content = re.sub(r'\[TABLE_\d+\]', '', text_content)
    text_content = re.sub(r'\[IMAGE_\d+\]', '', text_content)
    
    # Remove any remaining HTML tags (including table tags that might not have been extracted)
    # This ensures we don't show HTML code in Excel - only clean text
    soup_text = BeautifulSoup(text_content, 'html.parser')
    # Remove all HTML tags but keep text content, preserving line breaks
    text_content = soup_text.get_text(separator='\n', strip=False)
    
    # Extract and remove markdown tables (they will be shown as Excel tables, not in text)
    # Markdown tables have pattern: | col1 | col2 | ... followed by |---|---| and data rows
    markdown_table_pattern = r'\|[^\n]+\|\s*\n\|[-\s:|]+\|\s*\n(?:\|[^\n]+\|\s*\n?)+'
    markdown_tables = re.findall(markdown_table_pattern, text_content)
    for table in markdown_tables:
        text_content = text_content.replace(table, '')
    
    # Remove markdown headers
    text_content = re.sub(r'^#+\s+', '', text_content, flags=re.MULTILINE)
    # Remove markdown bold/italic
    text_content = re.sub(r'\*\*([^*]+)\*\*', r'\1', text_content)
    text_content = re.sub(r'\*([^*]+)\*', r'\1', text_content)
    text_content = re.sub(r'__([^_]+)__', r'\1', text_content)
    text_content = re.sub(r'_([^_]+)_', r'\1', text_content)
    # Remove markdown links
    text_content = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text_content)
    # Remove markdown code blocks
    text_content = re.sub(r'```[\s\S]*?```', '', text_content)
    text_content = re.sub(r'`([^`]+)`', r'\1', text_content)
    # Remove markdown lists markers
    text_content = re.sub(r'^\s*[-*+]\s+', '', text_content, flags=re.MULTILINE)
    text_content = re.sub(r'^\s*\d+\.\s+', '', text_content, flags=re.MULTILINE)
    # Remove markdown blockquotes
    text_content = re.sub(r'^>\s+', '', text_content, flags=re.MULTILINE)
    
    # Remove lines that are duplicate table data
    # Keep only narrative text (sentences/paragraphs), remove structured data that's already in tables
    lines = text_content.split('\n')
    filtered_lines = []
    for line in lines:
        line_stripped = line.strip()
        # Skip empty lines
        if not line_stripped:
            continue
        
        # Check if this line is table-related data that should be removed
        should_remove = False
        
        # Remove lines that are exact matches with table headers (like "Portfolio Code", "Institution Name")
        if line_stripped in table_header_names:
            should_remove = True
        # Remove lines that are exact matches with table data values (standalone values)
        elif line_stripped in table_data_values:
            should_remove = True
        # Remove lines that are simple label-value pairs where the value is table data
        # Pattern: "Label: Value" where Value is in table_data_values
        elif ':' in line_stripped:
            parts = line_stripped.split(':', 1)
            if len(parts) == 2:
                value_part = parts[1].strip()
                if value_part in table_data_values:
                    should_remove = True
        
        # Keep the line if it's narrative text (contains sentences, not just data)
        if not should_remove:
            # Keep lines that are clearly narrative (have punctuation, multiple words, etc.)
            word_count = len(line_stripped.split())
            has_punctuation = any(char in line_stripped for char in ['.', '!', '?', ',', ';', ':'])
            
            # Keep if it's a sentence/paragraph (has punctuation or multiple words)
            if has_punctuation or word_count > 4:
                filtered_lines.append(line)
            # Also keep short lines that don't match table data (might be section headers or emphasis)
            elif word_count <= 4 and line_stripped not in table_data_values and line_stripped not in table_header_names:
                filtered_lines.append(line)
    
    text_content = '\n'.join(filtered_lines)
    
    # Clean up extra whitespace and normalize
    text_content = re.sub(r'\n\s*\n\s*\n+', '\n\n', text_content)
    text_content = re.sub(r'[ \t]+', ' ', text_content)  # Replace multiple spaces/tabs with single space
    text_content = text_content.strip()

    # Add text content starting from row 1
    current_row = 1
    if text_content:
        ws[f'A{current_row}'] = 'Content'
        ws[f'A{current_row}'].font = Font(bold=True, size=11)
        ws[f'A{current_row}'].fill = PatternFill(start_color="E7E6E6", end_color="E7E6E6", fill_type="solid")
        ws[f'A{current_row}'].border = border
        current_row += 1
        
        # Split text into paragraphs and add to cells
        paragraphs = [p.strip() for p in text_content.split('\n\n') if p.strip()]
        for para in paragraphs:
            # Handle long paragraphs by wrapping
            lines = para.split('\n')
            for line in lines:
                if line.strip():
                    ws[f'A{current_row}'] = line.strip()
                    ws[f'A{current_row}'].alignment = Alignment(wrap_text=True, vertical='top')
                    ws[f'A{current_row}'].border = Border(
                        left=Side(style='thin'),
                        right=Side(style='thin'),
                        top=Side(style='thin'),
                        bottom=Side(style='thin')
                    )
                    current_row += 1
            current_row += 1  # Add spacing between paragraphs

    # Process HTML tables (both pre-extracted and markdown-converted)
    if all_tables:
        for table_idx, table_html in enumerate(all_tables):
            if current_row > 1:
                current_row += 1  # Add spacing before table if not first element
            
            soup = BeautifulSoup(table_html, 'html.parser')
            table = soup.find('table')
            
            if table:
                # Process table for header splitting and cell wrapping
                soup = process_table_headers(soup)
                soup = process_table_cells_for_wrapping(soup)
                table = soup.find('table')
                
                # Extract headers
                headers = []
                header_row = table.find('thead')
                if header_row:
                    header_cells = header_row.find_all(['th', 'td'])
                    headers = []
                    for cell in header_cells:
                        # Get text, preserving line breaks
                        text = cell.get_text(separator='\n', strip=True)
                        headers.append(text)
                else:
                    # Try first row as headers
                    first_row = table.find('tr')
                    if first_row:
                        header_cells = first_row.find_all(['th', 'td'])
                        headers = []
                        for cell in header_cells:
                            text = cell.get_text(separator='\n', strip=True)
                            headers.append(text)

                # Calculate responsive column widths
                widths = calculate_responsive_column_widths(soup)
                num_cols = len(headers) if headers else 0

                # Write headers
                if headers:
                    for col_idx, header in enumerate(headers, start=1):
                        cell = ws.cell(row=current_row, column=col_idx, value=header)
                        cell.font = header_font
                        cell.fill = header_fill
                        cell.border = border
                        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
                    # Set compact row height for header
                    ws.row_dimensions[current_row].height = 20
                    current_row += 1

                # Extract and write data rows
                tbody = table.find('tbody')
                rows = tbody.find_all('tr') if tbody else table.find_all('tr')
                
                # Skip header row if it was used as header
                if not header_row and rows:
                    rows = rows[1:]
                
                # Track content characteristics per column for intelligent width calculation
                header_lengths = [len(h) for h in headers] if headers else []
                max_content_lengths = header_lengths.copy() if header_lengths else []
                min_content_lengths = [float('inf')] * num_cols
                all_values_per_col = [[] for _ in range(num_cols)]
                
                for row in rows:
                    cells = row.find_all(['td', 'th'])
                    for col_idx, cell in enumerate(cells, start=1):
                        if col_idx <= len(headers):
                            cell_value = cell.get_text(separator=' ', strip=True)
                            
                            # Store value for analysis
                            all_values_per_col[col_idx - 1].append(cell_value)
                            
                            # For wrapped content, use the longest line
                            if '\n' in cell_value:
                                lines = cell_value.split('\n')
                                cell_value = max(lines, key=len) if lines else cell_value
                            
                            # Apply intelligent wrapping for long content
                            if len(cell_value) > 30:
                                # Use intelligent wrapping that breaks at optimal points
                                words = cell_value.split()
                                wrapped_lines = []
                                current_line = []
                                current_length = 0
                                max_width = 30
                                
                                for word in words:
                                    word_len = len(word)
                                    
                                    # If word itself is too long, break it intelligently
                                    if word_len > max_width:
                                        # Break long word at optimal point
                                        break_point = find_optimal_break_point(word, max_width)
                                        if break_point < len(word):
                                            first_part = word[:break_point]
                                            second_part = word[break_point:]
                                            
                                            # Add first part to current line if it fits
                                            if current_length + len(first_part) + 1 <= max_width and current_line:
                                                current_line.append(first_part + '-')
                                                wrapped_lines.append(' '.join(current_line))
                                                current_line = [second_part]
                                                current_length = len(second_part)
                                            else:
                                                if current_line:
                                                    wrapped_lines.append(' '.join(current_line))
                                                current_line = [first_part + '-']
                                                current_length = len(first_part) + 1
                                                # Handle remaining part
                                                while len(second_part) > max_width:
                                                    bp = find_optimal_break_point(second_part, max_width)
                                                    wrapped_lines.append(second_part[:bp] + '-')
                                                    second_part = second_part[bp:]
                                                current_line.append(second_part)
                                                current_length += len(second_part) + 1
                                        else:
                                            # Can't break, add as is
                                            if current_length + word_len + 1 > max_width and current_line:
                                                wrapped_lines.append(' '.join(current_line))
                                                current_line = [word]
                                                current_length = word_len
                                            else:
                                                current_line.append(word)
                                                current_length += word_len + 1
                                    else:
                                        # Regular word
                                        if current_length + word_len + 1 > max_width and current_line:
                                            wrapped_lines.append(' '.join(current_line))
                                            current_line = [word]
                                            current_length = word_len
                                        else:
                                            current_line.append(word)
                                            current_length += word_len + 1
                                
                                if current_line:
                                    wrapped_lines.append(' '.join(current_line))
                                
                                cell_value = '\n'.join(wrapped_lines)
                            
                            excel_cell = ws.cell(row=current_row, column=col_idx, value=cell_value)
                            excel_cell.border = border
                            excel_cell.alignment = Alignment(horizontal='left', vertical='top', wrap_text=True)
                            
                            # Update max and min content length for this column
                            if col_idx <= len(max_content_lengths):
                                content_len = len(cell_value.split('\n')[0]) if '\n' in cell_value else len(cell_value)
                                max_content_lengths[col_idx - 1] = max(max_content_lengths[col_idx - 1], content_len)
                                min_content_lengths[col_idx - 1] = min(min_content_lengths[col_idx - 1], content_len)
                    # Set compact row height for data rows (auto-adjusts if content wraps)
                    ws.row_dimensions[current_row].height = 15
                    current_row += 1
                
                # Calculate required widths per column (actual used width only - NO minimum width)
                required_widths = []
                
                for col_idx in range(1, num_cols + 1):
                    idx = col_idx - 1
                    
                    if idx < len(max_content_lengths):
                        header_len = header_lengths[idx] if idx < len(header_lengths) else 0
                        max_len = max_content_lengths[idx]
                        
                        # Actual required width (max of header and data) - no minimum constraint
                        actual_required = max(header_len, max_len)
                        
                        # Add small padding (1 char) for readability, but no minimum width
                        if actual_required > 0:
                            actual_required += 1  # Just 1 char padding
                        else:
                            actual_required = 2  # Absolute minimum for empty columns
                        
                        required_widths.append(actual_required)
                    else:
                        required_widths.append(5)  # Default for missing columns
                
                # Use actual required widths directly - no minimum width constraints
                optimized_widths = required_widths.copy()
                
                # Apply optimized widths
                for col_idx in range(1, num_cols + 1):
                    col_letter = get_column_letter(col_idx)
                    idx = col_idx - 1
                    
                    if idx < len(optimized_widths):
                        width = optimized_widths[idx]
                        # Only ensure absolute minimum for readability (2 chars)
                        width = max(width, 2)
                        # Cap maximum width
                        width = min(width, 50)
                        ws.column_dimensions[col_letter].width = width
                    else:
                        ws.column_dimensions[col_letter].width = 5

    # Adjust column widths for text content columns (if any)
    if ws.max_column > 0:
        # Ensure first column has reasonable width if it contains text
        if ws.column_dimensions['A'].width is None or ws.column_dimensions['A'].width < 20:
            ws.column_dimensions['A'].width = 50

    # Save to bytes
    excel_buffer = io.BytesIO()
    wb.save(excel_buffer)
    excel_buffer.seek(0)
    return excel_buffer.getvalue()


def download_message_as_file(message: dict, download_type: str):
    """
    Generate and return a downloadable file response for a message.

    Args:
        message: Message dictionary from database
        download_type: 'pdf' or 'excel'

    Returns:
        Flask Response with file data
    """
    if download_type.lower() == 'pdf':
        file_data = generate_pdf_from_message(message)
        content_type = 'application/pdf'
        extension = 'pdf'
    elif download_type.lower() == 'excel':
        file_data = generate_excel_from_message(message)
        content_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        extension = 'xlsx'
    else:
        raise ValueError(f"Invalid download type: {download_type}")

    # Generate filename
    message_id = message.get('id', 'message').replace('message_', '')
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"message_{message_id}_{timestamp}.{extension}"

    return Response(
        file_data,
        mimetype=content_type,
        headers={
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Length': str(len(file_data))
        }
    )
