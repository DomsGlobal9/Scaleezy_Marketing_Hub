import os
import glob

def replace_urls(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Replace single quote instances
    content = content.replace("'http://127.0.0.1:8000", "import.meta.env.VITE_API_URL + '")
    
    # Replace double quote instances
    content = content.replace('"http://127.0.0.1:8000', 'import.meta.env.VITE_API_URL + "')

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)

for tsx_file in glob.glob("src/routes/**/*.tsx", recursive=True):
    replace_urls(tsx_file)

print("Done replacing URLs!")
