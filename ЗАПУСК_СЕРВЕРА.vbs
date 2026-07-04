' Запуск Laser ERP: открывает CMD в папке проекта и запускает run.bat
' Двойной щелчок по этому файлу — если run.bat не срабатывает
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WshShell.Run "cmd /k """ & WshShell.CurrentDirectory & "\run.bat""", 1, True
