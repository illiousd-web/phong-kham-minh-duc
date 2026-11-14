' Minh Duc - tro giup cho CAI_MAY_TRAM.bat (chay duoc tren Windows 7 SP1, 10, 11).
' Tep chi dung ky tu ASCII; ten tieng Viet ghep bang ChrW nen khong phu thuoc bang ma.
'   cscript //nologo MayTram.vbs elevate "<duong dan .bat>" [tham so...]  -> chay lai .bat voi quyen Administrator
'   cscript //nologo MayTram.vbs shortcut "<https://IP:cong>"             -> bieu tuong Desktop chung (Chrome --app, khong co thi Edge)
' Ma ket qua: 0 = xong, 2 = sai tham so, 3 = khong thay Chrome/Edge, 4 = khong tao duoc bieu tuong.
Option Explicit
Dim args, shell, fso
Set args = WScript.Arguments
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
If args.Count < 2 Then WScript.Quit 2

Select Case LCase(args(0))
    Case "elevate"
        Dim rest, i
        rest = ""
        For i = 2 To args.Count - 1
            rest = rest & " """ & args(i) & """"
        Next
        CreateObject("Shell.Application").ShellExecute args(1), rest, "", "runas", 1
        WScript.Quit 0
    Case "shortcut"
        WScript.Quit MakeShortcut(args(1))
    Case Else
        WScript.Quit 2
End Select

Function FindBrowser()
    Dim candidates, c, env
    Set env = shell.Environment("PROCESS")
    candidates = Array( _
        env("ProgramFiles") & "\Google\Chrome\Application\chrome.exe", _
        env("ProgramFiles(x86)") & "\Google\Chrome\Application\chrome.exe", _
        env("LOCALAPPDATA") & "\Google\Chrome\Application\chrome.exe", _
        env("ProgramFiles(x86)") & "\Microsoft\Edge\Application\msedge.exe", _
        env("ProgramFiles") & "\Microsoft\Edge\Application\msedge.exe")
    FindBrowser = ""
    For Each c In candidates
        If Len(c) > 30 Then
            If fso.FileExists(c) Then
                FindBrowser = c
                Exit Function
            End If
        End If
    Next
End Function

Function MakeShortcut(url)
    Dim browser, desktop, tmpPath, finalPath, sc, attempt
    browser = FindBrowser()
    If browser = "" Then
        WScript.Echo "KHONG THAY Chrome hoac Edge."
        MakeShortcut = 3
        Exit Function
    End If
    desktop = shell.SpecialFolders("AllUsersDesktop")
    ' "Phong kham Minh Duc" co dau: P h o-huyen n g ... D-gach u-moc-sac c
    finalPath = desktop & "\Ph" & ChrW(242) & "ng kh" & ChrW(225) & "m Minh " & ChrW(272) & ChrW(7913) & "c.lnk"
    tmpPath = desktop & "\MinhDuc-tam.lnk"
    On Error Resume Next
    If fso.FileExists(tmpPath) Then
        Err.Clear
        fso.DeleteFile tmpPath, True
        If Err.Number <> 0 Then
            WScript.Echo "LOI tao bieu tuong: " & Err.Description
            MakeShortcut = 4
            Exit Function
        End If
    End If
    Err.Clear
    Set sc = shell.CreateShortcut(tmpPath)
    sc.TargetPath = browser
    sc.Arguments = "--app=" & url
    sc.Description = "Phan mem Phong kham da khoa Minh Duc"
    sc.IconLocation = browser & ",0"
    If Err.Number <> 0 Then
        WScript.Echo "LOI tao bieu tuong: " & Err.Description
        MakeShortcut = 4
        Exit Function
    End If
    Err.Clear
    sc.Save
    If Err.Number <> 0 Then
        WScript.Echo "LOI tao bieu tuong: " & Err.Description
        MakeShortcut = 4
        Exit Function
    End If
    For attempt = 1 To 3
        Err.Clear
        fso.CopyFile tmpPath, finalPath, True
        If Err.Number = 0 Then Exit For
        If attempt = 3 Then
            WScript.Echo "LOI tao bieu tuong: " & Err.Description
            MakeShortcut = 4
            Exit Function
        End If
        WScript.Sleep 1000
    Next
    Err.Clear
    fso.DeleteFile tmpPath, True
    If Err.Number <> 0 Then
        WScript.Echo "LOI tao bieu tuong: " & Err.Description
        MakeShortcut = 4
        Exit Function
    End If
    On Error GoTo 0
    ' Kiem lai: tep .lnk phai that su ton tai sau khi tao.
    If Not fso.FileExists(finalPath) Then
        WScript.Echo "LOI: khong thay tep bieu tuong sau khi tao."
        MakeShortcut = 4
        Exit Function
    End If
    WScript.Echo "OK " & browser
    MakeShortcut = 0
End Function
