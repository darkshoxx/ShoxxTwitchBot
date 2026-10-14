demos_path = r"C:\Users\Daniel\Desktop\Weekend Demos\usual Demos"
target_file = r"C:\Code\GithubRepos\ShoxxTwitchBot\stream-overlay\public\assets\files.txt"

from pathlib import Path
import re

def process_demo_files(demos_paths: str, target_file: str) -> None:
    folder = Path(demos_paths)
    print(f"Scanning folder: {folder.resolve()}")
    
    if not folder.exists() or not folder.is_dir():
        print(f"Error: Folder path does not exist or is not a directory: {demos_paths}")
        return

    # Sort files by date of creation
    files = sorted([f for f in folder.iterdir() if f.is_file()], key=lambda f: f.stat().st_ctime)
    processed_names = []

    for file_path in files:
        original_name = file_path.name
        
        # 2. Remove file extensions
        name = file_path.stem
        
        # 3. Remove the word "Demo"
        name = re.sub(r'\bDemo\b', '', name, flags=re.IGNORECASE)
        
        # 4. Replace double whitespaces and strip
        name = re.sub(r'\s+', ' ', name).strip()
        
        print(f"Processed: '{original_name}' -> '{name}'")
        processed_names.append(name)

    print(f"Writing {len(processed_names)} items to target file: {target_file}")
    with open(target_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(processed_names) + ('\n' if processed_names else ''))
    print("Write complete.")

process_demo_files(demos_paths=demos_path, target_file=target_file)