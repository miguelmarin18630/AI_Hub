' AI Hub - tunel de Cloudflare sin ventana de consola
' Doble clic aqui para publicar AI Hub en https://aihub.marinweb.org
Option Explicit

Dim shell, fso, baseDir

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

baseDir = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = baseDir

shell.Run "cloudflared.exe tunnel run aihub", 0, False
