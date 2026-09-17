import tkinter as tk
from views_pg import GRPAppPG

def main():
    root = tk.Tk()
    app = GRPAppPG(root)
    root.mainloop()

if __name__ == "__main__":
    main()