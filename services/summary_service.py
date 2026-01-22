import os
import re
import hashlib
from typing import Optional
from openai import AzureOpenAI
from cosmos_interface import conversation_container
from azure.cosmos.exceptions import CosmosResourceNotFoundError

# Reuse OpenAI configuration from chat_service
# Model name - should match your Azure OpenAI deployment name
# Can be overridden via OPENAI_MODEL environment variable
OPENAI_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4.1')
OPENAI_ENDPOINT = 'https://cynthetixopenai.openai.azure.com/'
OPENAI_API_KEY = os.environ.get('CYNTHETIX_OPENAI_API_KEY')
OPENAI_API_VERSION = '2025-03-01-preview'

def _get_openai_client():
    """Get Azure OpenAI client instance."""
    return AzureOpenAI(
        api_version=OPENAI_API_VERSION,
        azure_endpoint=OPENAI_ENDPOINT,
        api_key=OPENAI_API_KEY
    )

def _extract_text_from_html(html_content: str) -> str:
    """
    Extract readable text from HTML content.
    Converts tables and other HTML elements to plain text with actual data values.
    """
    if not html_content:
        return ""
    
    # Remove script and style elements
    html_content = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    html_content = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    
    # Convert tables to structured text with actual data
    def table_to_text(match):
        table_html = match.group(0)
        
        # Extract headers - check thead first, then first row
        headers = []
        header_row = re.search(r'<thead[^>]*>(.*?)</thead>', table_html, re.DOTALL | re.IGNORECASE)
        if header_row:
            header_cells = re.findall(r'<th[^>]*>(.*?)</th>', header_row.group(1), re.DOTALL | re.IGNORECASE)
            headers = [re.sub(r'<[^>]+>', '', cell).strip() for cell in header_cells]
        else:
            # Try first row for headers
            first_row_match = re.search(r'<tr[^>]*>(.*?)</tr>', table_html, re.DOTALL | re.IGNORECASE)
            if first_row_match:
                header_cells = re.findall(r'<th[^>]*>(.*?)</th>', first_row_match.group(1), re.DOTALL | re.IGNORECASE)
                if header_cells:
                    headers = [re.sub(r'<[^>]+>', '', cell).strip() for cell in header_cells]
        
        # Extract data rows
        data_rows = []
        tbody = re.search(r'<tbody[^>]*>(.*?)</tbody>', table_html, re.DOTALL | re.IGNORECASE)
        if tbody:
            row_matches = re.findall(r'<tr[^>]*>(.*?)</tr>', tbody.group(1), re.DOTALL | re.IGNORECASE)
        else:
            # If no tbody, get all rows (skip header row if it has th tags)
            all_rows = re.findall(r'<tr[^>]*>(.*?)</tr>', table_html, re.DOTALL | re.IGNORECASE)
            # Skip first row if it contains headers
            if headers and all_rows:
                row_matches = all_rows[1:]
            else:
                row_matches = all_rows
        
        for row in row_matches:
            # Extract both td and th cells (in case some rows mix them)
            cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.DOTALL | re.IGNORECASE)
            cell_texts = [re.sub(r'<[^>]+>', '', cell).strip() for cell in cells]
            # Filter out empty cells and skip rows that look like headers
            cell_texts = [c for c in cell_texts if c]
            if cell_texts and len(cell_texts) > 1:  # At least 2 cells to be a data row
                data_rows.append(cell_texts)
        
        # Build structured table description with actual data
        if not data_rows:
            return "Empty table."
        
        desc = "TABLE DATA:\n"
        if headers:
            desc += f"Columns: {', '.join(headers)}\n"
        desc += f"Total rows: {len(data_rows)}\n\n"
        
        # Include all row data with headers mapped to values
        for i, row in enumerate(data_rows, 1):
            if headers and len(headers) == len(row):
                # Format as key-value pairs for better readability
                row_data = []
                for j, header in enumerate(headers):
                    if j < len(row):
                        row_data.append(f"{header}: {row[j]}")
                desc += f"Row {i}: {' | '.join(row_data)}\n"
            else:
                # Just list values if headers don't match
                desc += f"Row {i}: {' | '.join(row)}\n"
        
        return desc
    
    # Replace tables with structured data
    html_content = re.sub(r'<table[^>]*>.*?</table>', table_to_text, html_content, flags=re.DOTALL | re.IGNORECASE)
    
    # Remove remaining HTML tags
    text = re.sub(r'<[^>]+>', ' ', html_content)
    
    # Clean up whitespace but preserve structure
    text = re.sub(r'[ \t]+', ' ', text)  # Multiple spaces to single space
    text = re.sub(r'\n[ \t]*\n', '\n\n', text)  # Preserve paragraph breaks
    
    return text.strip()

def _check_existing_summary(response_id: str) -> Optional[str]:
    """
    Check if a summary already exists for a given response_id.
    Returns the existing summary if found, None otherwise.
    """
    if not response_id:
        return None
    
    try:
        # Query for message with this response_id
        query = """
        SELECT c.tts_summary, c.id
        FROM c
        WHERE c.type = 'message' AND c.response_id = @response_id AND c.role = 'assistant'
        ORDER BY c.created_at DESC
        """
        
        from typing import List
        parameters: List[dict[str, object]] = [
            {"name": "@response_id", "value": response_id}
        ]
        
        items = list(conversation_container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True
        ))
        
        if items and items[0].get("tts_summary"):
            return items[0]["tts_summary"]
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Error checking existing summary for response_id {response_id}: {e}")
    
    return None

def generate_tts_summary(content: str, response_id: str = None) -> Optional[str]:
    """
    Generate a TTS-friendly summary of the message content.
    
    Args:
        content: The message content (may contain HTML, text, tables, etc.)
        response_id: Optional response_id to check for existing summary
    
    Returns:
        TTS-friendly summary string, or None if generation fails
    """
    if not content or not content.strip():
        return None
    
    # Check for existing summary first
    if response_id:
        existing_summary = _check_existing_summary(response_id)
        if existing_summary:
            return existing_summary
    
    try:
        # Extract text from HTML if needed
        text_content = _extract_text_from_html(content)
        
        # If extracted text is too short or empty, use original content
        if len(text_content.strip()) < 50:
            text_content = content
            # Still try to remove HTML tags
            text_content = re.sub(r'<[^>]+>', ' ', text_content)
            text_content = re.sub(r'\s+', ' ', text_content).strip()
        
        # Truncate if too long (to avoid token limits)
        max_input_length = 8000  # Leave room for prompt
        if len(text_content) > max_input_length:
            text_content = text_content[:max_input_length] + "..."
        
        # Create summarization prompt
        prompt = f"""You are a text-to-speech summary generator. Create a factual, data-driven summary of the following content that will be read aloud by Azure TTS.

CRITICAL REQUIREMENTS:
1. ALWAYS include specific numbers, percentages, dollar amounts, and exact values from tables
2. For tables: Mention the highest and lowest values, largest and smallest percentages, top and bottom entries with their specific details
3. Include specific names, codes, identifiers, portfolio names, instrument names, and key metrics from the data
4. For financial tables: Include market values, percentages of net worth, quantities, portfolio codes, asset classes
5. DO NOT include conversational phrases like "just let me know", "if you need", "let me know", "if you want", or any invitations for further action
6. DO NOT include phrases about providing more details, custom summaries, or breakdowns
7. Focus ONLY on factual data presentation - what the data shows, not what can be done with it
8. Extract and mention ALL key data points from ALL content types (text, tables, lists, etc.)

Content may include:
- Plain text (extract key facts, numbers, dates, names)
- Tables with actual data (MUST extract and mention specific values, highest/lowest entries)
- HTML graphs/charts (describe visual patterns with specific numbers)
- Lists and structured data (include all relevant items)

Guidelines:
- Use clear, professional language suitable for speech
- Avoid special characters that don't read well in TTS
- For tables: ALWAYS include:
  * Specific dollar amounts, percentages, quantities with their labels
  * Highest/lowest values with their corresponding portfolio codes, instrument names
  * Portfolio codes, institution names, instrument names, asset classes mentioned
  * Market values and percentages of net worth for each entry
  * Top entries with full details (portfolio, instrument, value, percentage)
- For all content: Extract and mention specific facts, numbers, names, dates
- Adapt length based on complexity:
  * Simple content: 2-3 sentences (100-150 words)
  * Medium complexity: 3-4 sentences (150-200 words)
  * Complex data with tables: 4-6 sentences (200-300 words) - MUST include key numbers
- Write in a natural, flowing style that sounds good when spoken
- Remove any HTML tags or formatting codes from your response
- NO conversational invitations or action requests

Content to summarize:
{text_content}

Provide only the factual summary text with specific data points, no additional formatting, explanations, or conversational phrases:"""

        # Call OpenAI API
        client = _get_openai_client()
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant that creates factual, data-driven summaries optimized for text-to-speech systems. Always include specific numbers, values, and data points from the content."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.7,
            max_tokens=400  # Increased to allow for detailed data summaries
        )
        
        summary = response.choices[0].message.content.strip()
        
        # Clean up summary - remove any remaining HTML or special formatting
        summary = re.sub(r'<[^>]+>', '', summary)
        summary = re.sub(r'\s+', ' ', summary).strip()
        
        # Remove common conversational phrases that shouldn't be in TTS summaries
        conversational_patterns = [
            r'\b(just\s+)?let\s+me\s+know\b[^.]*\.',
            r'\bif\s+you\s+need\b[^.]*\.',
            r'\bif\s+you\s+want\b[^.]*\.',
            r'\bI\s+can\s+provide\b[^.]*\.',
            r'\bjust\s+let\s+me\s+know\s+and\s+I\s+can\b[^.]*\.',
            r'\bto\s+fit\s+your\s+needs\b[^.]*\.',
            r'\bcustomized\s+summary\b[^.]*\.',
            r'\bmore\s+detail[^.]*\.',
            r'\bbreakdown\s+by[^.]*\.',
            r'\bgrouped\s+by[^.]*\.',
            r'\bparticular\s+aggregation[^.]*\.',
            r'\bfull\s+listing[^.]*\.',
            r'\bexposures\s+grouped[^.]*\.',
        ]
        
        for pattern in conversational_patterns:
            summary = re.sub(pattern, '', summary, flags=re.IGNORECASE)
        
        # Clean up any double spaces, periods, or trailing commas
        summary = re.sub(r'\s+', ' ', summary)
        summary = re.sub(r'\.\s*\.', '.', summary)
        summary = re.sub(r',\s*\.', '.', summary)
        summary = summary.strip()
        
        # Remove trailing sentence fragments
        summary = re.sub(r'\s+[a-z][^.]*$', '', summary, flags=re.IGNORECASE)
        
        return summary if summary else None
        
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error generating TTS summary: {e}")
        return None

