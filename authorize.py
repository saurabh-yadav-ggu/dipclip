import subprocess
import sys
import os
from pathlib import Path

def main():
    print("Installing yt-dlp and yt-dlp-youtube-oauth2 locally...")
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp", "yt-dlp-youtube-oauth2"], check=True)
    except Exception as e:
        print(f"Warning: Failed to install packages via pip: {e}")
        print("Please make sure you have pip installed and run: pip install yt-dlp yt-dlp-youtube-oauth2")
        sys.exit(1)

    print("\nStarting YouTube OAuth2 authentication...")
    print("Please follow the instructions on the screen.")
    print("You will be given a code and a link (google.com/device) to authorize this app.")
    print("Log in with any Google account (it does not need to be your main account).\n")

    # Run dummy extraction to trigger OAuth2
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
        
        # Read the token
        token_path = Path("./cache_temp/youtube-oauth2/token.json")
        if token_path.exists():
            with open(token_path, "r") as f:
                token_data = f.read()
            print("\n" + "="*50)
            print("SUCCESSFULLY AUTHENTICATED!")
            print("="*50)
            print("Copy the entire JSON below (including the curly braces {}):")
            print("\n" + token_data + "\n")
            print("="*50)
            print("Paste this value into your Railway Environment Variable:")
            print("Name: YTDLP_OAUTH2_TOKEN")
            print("="*50)
            
            # Clean up temp cache directory
            try:
                import shutil
                shutil.rmtree("./cache_temp")
            except Exception:
                pass
        else:
            print("\nError: Authentication succeeded but token.json was not found in cache_temp.")
    except Exception as e:
        print(f"\nError during authorization: {e}")

if __name__ == "__main__":
    main()
