import os
import sys
import gc

def find_py_files(base_path="/sd"):
    py_files = []
    try:
        for entry in os.listdir(base_path):
            full_path = f"{base_path}/{entry}"
            try:
                mode = os.stat(full_path)[0]
                if mode & 0x4000:  # Directory
                    sub_files = find_py_files(full_path)
                    py_files.extend(sub_files)
                elif entry.endswith(".py"):
                    relative_path = full_path[len("/sd/"):-3]  # remove /sd/ and .py
                    py_files.append(relative_path)
            except Exception as e:
                print(f"Error reading {full_path}: {e}")
    except Exception as e:
        print(f"Error listing {base_path}: {e}")
    return py_files

def delete_file(script_path, base_path="/sd"):
    """Delete a file with confirmation"""
    try:
        full_path = f"{base_path}/{script_path}.py"
        
        # Check if file exists
        try:
            os.stat(full_path)
        except OSError:
            print(f"File not found: {script_path}.py")
            return False
        
        # Show file info before deletion
        try:
            stat = os.stat(full_path)
            size = stat[6]  # file size
            print(f"\nFile: {script_path}.py")
            print(f"Size: {size} bytes")
            print(f"Path: {full_path}")
        except:
            pass
        
        # Confirmation prompt
        print(f"\nAre you sure you want to delete '{script_path}.py'?")
        print("This action cannot be undone!")
        confirm = input("Delete file? (y/N): ").strip().lower()
        
        if confirm == "y":
            os.remove(full_path)
            print(f"File '{script_path}.py' has been deleted.")
            return True
        else:
            print("Deletion cancelled.")
            return False
            
    except Exception as e:
        print(f"Error deleting {script_path}: {e}")
        return False

def run_script(script_path, base_path="/sd"):
    try:
        full_path = f"{base_path}/{script_path}.py"
        
        # First, try to load the script content
        with open(full_path) as f:
            script_content = f.read()
        
        # Create a new namespace for running the script
        script_globals = {
            '__name__': '__main__',
            '__file__': full_path,
        }
        
        # Add standard modules to the namespace
        for module_name in ['os', 'sys', 'gc']:
            if module_name in globals():
                script_globals[module_name] = globals()[module_name]
        
        # Execute the script in the new namespace
        exec(script_content, script_globals)
        
        # If the script has a main_menu function and it wasn't called by the script itself
        # (which might happen with guard statements), call it
        if 'main_menu' in script_globals and callable(script_globals['main_menu']):
            if 'main_executed' not in script_globals or not script_globals['main_executed']:
                print("No entry point called, executing main_menu()...")
                script_globals['main_menu']()
                script_globals['main_executed'] = True
                
    except Exception as e:
        print(f"Failed running {script_path}: {e}")

def flush_modules(exclude=("os", "sys", "gc")):
    flushed = []
    for name in list(sys.modules):
        if name not in exclude and not name.startswith("micropython"):
            sys.modules.pop(name, None)
            flushed.append(name)
    print(f"Flushed: {', '.join(flushed)}")

def show_memory():
    gc.collect()
    print(f"RAM Free: {gc.mem_free()} bytes")
    print(f"RAM Used: {gc.mem_alloc()} bytes")
    
    # Add storage space information
    try:
        # Get storage info for /sd
        stat = os.statvfs('/sd')
        block_size = stat[0]  # f_bsize - file system block size
        total_blocks = stat[2]  # f_blocks - total blocks in the filesystem
        free_blocks = stat[3]  # f_bfree - free blocks
        
        # Calculate total and free space in bytes
        total_space = block_size * total_blocks
        free_space = block_size * free_blocks
        used_space = total_space - free_space
        
        # Convert to more readable format (KB, MB)
        def format_bytes(bytes_val):
            if bytes_val >= 1024 * 1024:
                return f"{bytes_val / (1024 * 1024):.2f} MB"
            elif bytes_val >= 1024:
                return f"{bytes_val / 1024:.2f} KB"
            else:
                return f"{bytes_val} bytes"
        
        print("\nStorage on /sd:")
        print(f"Total: {format_bytes(total_space)}")
        print(f"Used:  {format_bytes(used_space)}")
        print(f"Free:  {format_bytes(free_space)}")
        print(f"Usage: {used_space / total_space * 100:.1f}%")
    except Exception as e:
        print(f"Error getting storage info: {e}")

def file_management_menu():
    """Sub-menu for file management operations"""
    while True:
        scripts = find_py_files()
        if not scripts:
            print("No Python files found.")
            input("Press Enter to return to main menu...")
            return
        
        print("\n=== File Management ===")
        for i, name in enumerate(scripts):
            print(f"{i + 1}: {name}.py")
        
        print("\nFile Operations:")
        print("D: Delete a file")
        print("E: Edit a file")
        print("B: Back to main menu")
        
        choice = input("\nEnter choice: ").strip().lower()
        
        if choice == "b":
            return
        elif choice == "d":
            print("\nSelect file to delete:")
            for i, name in enumerate(scripts):
                print(f"{i + 1}: {name}.py")
            
            delete_choice = input("\nEnter file number to delete: ").strip()
            try:
                index = int(delete_choice) - 1
                if 0 <= index < len(scripts):
                    delete_file(scripts[index])
                    input("Press Enter to continue...")
                else:
                    print("Invalid selection.")
                    input("Press Enter to continue...")
            except ValueError:
                print("Invalid input. Please enter a number.")
                input("Press Enter to continue...")
        elif choice == "e":
            print("\nSelect file to edit:")
            for i, name in enumerate(scripts):
                print(f"{i + 1}: {name}.py")
            
            edit_choice = input("\nEnter file number to edit: ").strip()
            try:
                index = int(edit_choice) - 1
                if 0 <= index < len(scripts):
                    import picocalc
                    picocalc.edit(f"/sd/{scripts[index]}.py")
                    input("Press Enter to continue...")
                else:
                    print("Invalid selection.")
                    input("Press Enter to continue...")
            except ValueError:
                print("Invalid input. Please enter a number.")
                input("Press Enter to continue...")
        else:
            print("Invalid choice.")
            input("Press Enter to continue...")

def main_menu():
    while True:
        scripts = find_py_files()
        print("\n=== PicoCalc Main Menu ===")
        for i, name in enumerate(scripts):
            print(f"{i + 1}: Run {name}")
        
        print("\nOptions:")
        print("X: Exit to prompt")
        print("R: Reload menu")
        print("F: Flush & reload modules")
        print("M: Memory status")
        print("T: File management")
        
        choice = input("\nEnter choice: ").strip().lower()
        
        if choice == "x":
            print("Exiting to prompt.")
            return
        elif choice == "r":
            print("Reloading menu...")
            continue
        elif choice == "f":
            flush_modules()
            continue
        elif choice == "m":
            show_memory()
            continue
        elif choice == "t":
            file_management_menu()
            continue
        else:
            try:
                index = int(choice) - 1
                if 0 <= index < len(scripts):
                    print(f"\nRunning {scripts[index]}...\n")
                    run_script(scripts[index])
                    input("\nDone. Press Enter to return to menu...")
                else:
                    print("Invalid selection.")
            except ValueError:
                print("Invalid input. Use number or option letter.")
                
# This helper variable will let us know if the main entry point was executed
main_executed = False

def check_run_main():
    """Helper function to run main_menu if this is the main script"""
    global main_executed
    if __name__ == "__main__" and not main_executed:
        main_menu()
        main_executed = True

# Two ways to run this script:
# 1. With guard statement
if __name__ == "__main__":
    main_menu()
    main_executed = True

# 2. Without guard statement (will only run if not already executed by guard)
check_run_main()
