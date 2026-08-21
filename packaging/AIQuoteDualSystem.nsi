Unicode True

!include "MUI2.nsh"
!include "LogicLib.nsh"

!ifndef StageDir
  !error "StageDir must be supplied by the build script"
!endif
!ifndef OutputDir
  !error "OutputDir must be supplied by the build script"
!endif

!define APP_NAME "AI 双报价系统"
!define APP_VERSION "2026.08.21.4"
!define APP_EXE "AIQuoteDualSystem_layout_v6.exe"
!define APP_ID "AIQuoteDualSystem.DualQuote.2026"
!define APP_REG_KEY "Software\AIQuoteDualSystem"
!define APP_UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}"

Var StartMenuFolder

Name "${APP_NAME}"
OutFile "${OutputDir}\AIQuoteDualSystem_Setup_v2026.08.21.4.exe"
InstallDir "$LOCALAPPDATA\Programs\AIQuoteDualSystem"
InstallDirRegKey HKCU "${APP_REG_KEY}" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 64
CRCCheck on
XPStyle on
ShowInstDetails show
ShowUninstDetails show
BrandingText "AI 双报价系统 · 公式法 × 快速法"
Icon "${StageDir}\AIQuoteDualSystem.ico"
WindowIcon on

VIProductVersion "2026.8.21.4"
VIAddVersionKey /LANG=2052 "ProductName" "AI 双报价系统"
VIAddVersionKey /LANG=2052 "CompanyName" "AI 双报价系统"
VIAddVersionKey /LANG=2052 "FileDescription" "AI 双报价系统安装程序"
VIAddVersionKey /LANG=2052 "FileVersion" "2026.08.21.4"
VIAddVersionKey /LANG=2052 "ProductVersion" "2026.08.21.4"
VIAddVersionKey /LANG=2052 "LegalCopyright" "Copyright © 2026"

!define MUI_ABORTWARNING
!define MUI_ICON "${StageDir}\AIQuoteDualSystem.ico"
!define MUI_UNICON "${StageDir}\AIQuoteDualSystem.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP "${StageDir}\installer_sidebar.bmp"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_BITMAP "${StageDir}\installer_header.bmp"
!define MUI_WELCOMEPAGE_TITLE "欢迎安装 AI 双报价系统"
!define MUI_WELCOMEPAGE_TEXT "一个柜型，两种算法，报价结果清楚可核对。$\r$\n$\r$\n安装向导将复制已验证的桌面客户端。下一步可自由选择安装磁盘和目录。"
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "立即启动 AI 双报价系统"
!define MUI_FINISHPAGE_LINK "版本：v2026.08.21.4"
!define MUI_FINISHPAGE_LINK_LOCATION "https://github.com/daidai1007/ai-quote-dual-system/releases"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${StageDir}\PROJECT-LICENSE.txt"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_STARTMENU Application $StartMenuFolder
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

!insertmacro MUI_LANGUAGE "SimpChinese"

Section "主程序" SEC_MAIN
  SectionIn RO
  SetOutPath "$INSTDIR"
  File "${StageDir}\${APP_EXE}"
  File "${StageDir}\client_config.json"
  File "${StageDir}\PROJECT-LICENSE.txt"
  File "${StageDir}\README.txt"
  File "${StageDir}\release-manifest.json"
  File "${StageDir}\THIRD_PARTY_NOTICES.txt"
  File "${StageDir}\AIQuoteDualSystem.ico"
  File /r "${StageDir}\_internal"
  File /r "${StageDir}\runtime"

  CreateDirectory "$INSTDIR\output"
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  WriteRegStr HKCU "${APP_REG_KEY}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${APP_UNINSTALL_KEY}" "DisplayName" "${APP_NAME}"
  WriteRegStr HKCU "${APP_UNINSTALL_KEY}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "${APP_UNINSTALL_KEY}" "DisplayIcon" "$INSTDIR\AIQuoteDualSystem.ico"
  WriteRegStr HKCU "${APP_UNINSTALL_KEY}" "Publisher" "AI 双报价系统"
  WriteRegStr HKCU "${APP_UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${APP_UNINSTALL_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKCU "${APP_UNINSTALL_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${APP_UNINSTALL_KEY}" "NoRepair" 1

  !insertmacro MUI_STARTMENU_WRITE_BEGIN Application
    CreateDirectory "$SMPROGRAMS\$StartMenuFolder"
    CreateShortcut "$SMPROGRAMS\$StartMenuFolder\AI 双报价系统.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\AIQuoteDualSystem.ico"
    CreateShortcut "$SMPROGRAMS\$StartMenuFolder\卸载 AI 双报价系统.lnk" "$INSTDIR\Uninstall.exe"
    CreateShortcut "$DESKTOP\AI 双报价系统.lnk" "$INSTDIR\${APP_EXE}" "" "$INSTDIR\AIQuoteDualSystem.ico"
  !insertmacro MUI_STARTMENU_WRITE_END
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\AI 双报价系统.lnk"
  !insertmacro MUI_STARTMENU_GETFOLDER Application $StartMenuFolder
  Delete "$SMPROGRAMS\$StartMenuFolder\AI 双报价系统.lnk"
  Delete "$SMPROGRAMS\$StartMenuFolder\卸载 AI 双报价系统.lnk"
  RMDir "$SMPROGRAMS\$StartMenuFolder"

  Delete "$INSTDIR\${APP_EXE}"
  Delete "$INSTDIR\client_config.json"
  Delete "$INSTDIR\PROJECT-LICENSE.txt"
  Delete "$INSTDIR\README.txt"
  Delete "$INSTDIR\release-manifest.json"
  Delete "$INSTDIR\THIRD_PARTY_NOTICES.txt"
  Delete "$INSTDIR\AIQuoteDualSystem.ico"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir /r "$INSTDIR\_internal"
  RMDir /r "$INSTDIR\runtime"

  MessageBox MB_YESNO|MB_DEFBUTTON2 "是否同时删除本机生成的报价输出文件？" IDNO KeepOutput
    RMDir /r "$INSTDIR\output"
  KeepOutput:
  RMDir "$INSTDIR"

  DeleteRegKey HKCU "${APP_UNINSTALL_KEY}"
  DeleteRegKey HKCU "${APP_REG_KEY}"
SectionEnd
