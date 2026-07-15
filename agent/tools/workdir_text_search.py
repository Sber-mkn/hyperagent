from agent.tools.registry import tool
import os

@tool
def workdir_text_search(substring: str) -> str:
    """
    Search text files under /hyperagent/workdir for a case-insensitive substring.
    
    Args:
        substring: The text to search for (case-insensitive)
        
    Returns:
        Matches in format file:line:text
    """
    workdir = "/hyperagent/workdir"
    if not os.path.exists(workdir):
        return f"Workdir {workdir} does not exist"
    
    results = []
    substring_lower = substring.lower()
    
    try:
        for filename in os.listdir(workdir):
            filepath = os.path.join(workdir, filename)
            # Only process text files
            if os.path.isfile(filepath) and filename.endswith('.txt'):
                try:
                    with open(filepath, 'r', encoding='utf-8') as file:
                        for line_num, line in enumerate(file, 1):
                            if substring_lower in line.lower():
                                results.append(f"{filename}:{line_num}:{line.strip()}")
                except (UnicodeDecodeError, PermissionError):
                    # Skip files that can't be read as text
                    continue
    except Exception as e:
        return f"Error searching files: {str(e)}"
    
    return "\n".join(results) if results else "No matches found"