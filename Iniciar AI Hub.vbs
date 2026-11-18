' AI Hub · lanzador sin ventana de consola
' Doble clic aquí para abrir la aplicación.
Option Explicit

Dim shell, fso, baseDir, script

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

baseDir = fso.GetParentFolderName(WScript.ScriptFullName)
script = fso.BuildPath(baseDir, "AIHub.pyw")

If Not fso.FileExists(script) Then
    MsgBox "No encuentro AIHub.pyw junto a este lanzador.", 16, "AI Hub"
    WScript.Quit 1
End If

shell.CurrentDirectory = baseDir
On Error Resume Next
shell.Run """" & "pythonw.exe" & """ """ & script & """", 0, False
If Err.Number <> 0 Then
    Err.Clear
    shell.Run """" & "python.exe" & """ """ & script & """", 1, False
End If
On Error GoTo 0
