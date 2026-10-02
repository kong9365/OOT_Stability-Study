' Launch keepalive server with no console window
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = scriptDir
sh.Run """" & scriptDir & "\keepalive_server.bat""", 0, False
