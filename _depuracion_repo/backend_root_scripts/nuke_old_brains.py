import os
import shutil

def nuke_old_brains():
    brain_dir = r"C:\Users\halva\.gemini\antigravity\brain"
    current_sid = "2506e5a3-fb5b-43d9-8710-f32516caee8f"
    
    print(f"--- Nuking Old Brains in {brain_dir} ---")
    if not os.path.exists(brain_dir):
        print("Brain directory not found.")
        return

    items = os.listdir(brain_dir)
    deleted_count = 0
    for item in items:
        item_path = os.path.join(brain_dir, item)
        if os.path.isdir(item_path):
            if item == current_sid or item == "tempmediaStorage":
                print(f"Preserving: {item}")
                continue
            
            try:
                print(f"Deleting old brain: {item}...")
                shutil.rmtree(item_path)
                deleted_count += 1
            except Exception as e:
                print(f"Error deleting {item}: {e}")
    
    print(f"\nCleanup complete. Deleted {deleted_count} old conversations.")

if __name__ == "__main__":
    nuke_old_brains()
