' 배치 파일을 콘솔 창 없이(숨김) 실행한다.
' 사용법:  wscript run_hidden.vbs <batfile>
'   예)   wscript run_hidden.vbs run_webapp.bat
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = scriptDir
If WScript.Arguments.Count < 1 Then WScript.Quit 1
batPath = scriptDir & "\" & WScript.Arguments(0)
' 0 = 창 숨김, False = 종료 대기 안 함(백그라운드 상주)
sh.Run """" & batPath & """", 0, False
