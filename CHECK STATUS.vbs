' MBT POS — Quick Status Check
' Shows current service health in a popup.

Option Explicit
Dim oShell, oXML, oHTTP, sStatus, sMsg

Set oShell = CreateObject("WScript.Shell")

' Try to fetch status from the launcher's status endpoint
On Error Resume Next
Set oHTTP = CreateObject("MSXML2.XMLHTTP")
oHTTP.Open "GET", "http://localhost:5051/status", False
oHTTP.Send

Dim sResp, bFlask, bTunnel, bNet, sDomain
If oHTTP.Status = 200 Then
    ' Parse key values from JSON (simple string search)
    sResp = oHTTP.responseText
    bFlask  = InStr(sResp, """ok"": true") > 0
    bTunnel = InStr(sResp, """ok"": true") > 0  ' rough check
    bNet    = InStr(sResp, """internet"": true") > 0

    ' Extract domain
    Dim iD, iD2
    iD = InStr(sResp, """domain"":") + 10
    If iD > 10 Then
        iD2 = InStr(iD, sResp, """")
        If iD2 > iD Then sDomain = Mid(sResp, iD, iD2 - iD)
    End If
    If sDomain = "" Then sDomain = "edmuspos.mugobyte.com"

    sMsg = "MBT POS Web Service Status" & vbCrLf & vbCrLf & _
           "Flask (API):    " & IIf(bFlask, "Running", "DOWN") & vbCrLf & _
           "Tunnel:         " & IIf(bTunnel, "Running", "DOWN") & vbCrLf & _
           "Internet:       " & IIf(bNet, "Connected", "Offline") & vbCrLf & vbCrLf & _
           "Dashboard: https://" & sDomain & vbCrLf & _
           "Local:     http://localhost:5050"
Else
    sMsg = "Web service is not running." & vbCrLf & vbCrLf & _
           "Double-click START WEB.vbs to start it."
End If
On Error GoTo 0

MsgBox sMsg, 64, "MBT POS Status"

Function IIf(cond, a, b)
    If cond Then IIf = a Else IIf = b
End Function
