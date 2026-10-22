# Request to IT: remove the old machine-wide pyRevit

Copy the text below into an IT ticket or email. Change the parts in [brackets].

---

**Subject:** Please uninstall the old pyRevit (all users) on [PC name]

Hello,

Please uninstall the old pyRevit that is installed for all users on my PC [PC name]. This task needs admin rights, so I cannot do it.

- **Program to remove:** pyRevit [6.4], installed in `C:\Program Files\pyRevit-Master`. It shows in Settings > Apps > Installed apps as "pyRevit".
- **Also remove these files, if they stay after the uninstall:** `C:\ProgramData\Autodesk\Revit\Addins\<year>\pyRevit.addin`, for each Revit year (2024, 2025, 2026).
- **Do not remove:** pyRevit 7 in my user profile (`%APPDATA%\pyRevit-Master`) and the files in `%APPDATA%\Autodesk\Revit\Addins\<year>\`. I installed them without admin rights, and Revit uses them now.

**Why:**
- Revit uses pyRevit 7 from my profile, but command-line runs (`pyrevit run`) still load the old pyRevit [6.4] from Program Files.
- The old pyRevit installer also stops the per-user version from updating correctly.

**After the change:** I will run a check (archi-magic `am-doctor`) to confirm that only pyRevit 7 is in use. No restart is needed, other than closing Revit during the uninstall.

Thank you.
