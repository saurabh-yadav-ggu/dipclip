import subprocess
import sys
import os
from pathlib import Path

def main():
    print("Cleaning up obsolete plugin if present...")
    try:
        # Uninstall the obsolete plugin so it doesn't conflict with built-in OAuth2
        subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", "yt-dlp-youtube-oauth2"], check=False)
    except Exception as e:
        print(f"Warning during plugin cleanup: {e}")

    print("\nInstalling/Updating yt-dlp locally...")
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"], check=True)
    except Exception as e:
        print(f"Warning: Failed to upgrade yt-dlp: {e}")
        print("Please make sure you have pip installed and run: pip install --upgrade yt-dlp")
        sys.exit(1)

    print("\nStarting native YouTube OAuth2 authentication...")
    print("Please follow the instructions on the screen.")
    print("You will be given a code and a link (google.com/device) to authorize this app.")
    print("Log in with any Google account (it does not need to be your main account).\n")

    # Run dummy extraction to trigger native OAuth2
    cmd = [
        "yt-dlp",
        "--cache-dir", "./cache_temp",
        "--username", "oauth2",
        "--password", "",
        "https://www.youtube.com/watch?v=xeXV1KoX034",
        "--skip-download"
    ]

    try:
        subprocess.run(cmd, check=True)
        
        # Scan cache_temp recursively to find the token file
        token_data = None
        token_file_path = None
        for path in Path("./cache_temp").rglob("*"):
            if path.is_file() and "token_data" in path.name:
                token_file_path = path
                with open(path, "r") as f:
                    token_data = f.read()
                break

        if token_data:
            print("\n" + "="*50)
            print("SUCCESSFULLY AUTHENTICATED!")
            print("="*50)
            print("Copy the entire JSON below (including the curly braces {}):")
            print("\n" + token_data + "\n")
            print("="*50)
            print("Paste this value into your Vercel Environment Variable:")
            print("Name: YTDLP_OAUTH2_TOKEN")
            print("="*50)
            
            # Clean up temp cache directory
            try:
                import shutil
                shutil.rmtree("./cache_temp")
            except Exception:
                pass
        else:
            print("\nError: Authentication succeeded but token file was not found in cache_temp.")
            # Let's list files in cache_temp for debugging
            print("Files in cache_temp:")
            for path in Path("./cache_temp").rglob("*"):
                if path.is_file():
                    print(f"  - {path}")
    except Exception as e:
        print(f"\nError during authorization: {e}")

if __name__ == "__main__":
    main()
