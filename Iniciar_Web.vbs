' AI Hub Web · lanzador sin ventana de consola
' Doble clic aquí para abrir la versión web en el navegador.
Option Explicit

Dim shell, fso, baseDir

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

baseDir = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = baseDir
shell.Run "python.exe -m aihub.web run", 0, False