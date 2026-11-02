#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <string>
#include <vector>

static bool file(const std::wstring& path) {
    DWORD value=GetFileAttributesW(path.c_str());
    return value!=INVALID_FILE_ATTRIBUTES && !(value&FILE_ATTRIBUTE_DIRECTORY);
}
static std::wstring parent(std::wstring path) {
    const auto at=path.find_last_of(L"\\/");
    return at==std::wstring::npos ? L"":path.substr(0,at);
}
// Windows CRT argument quoting, including trailing slashes and embedded quotes.
static std::wstring quote(const std::wstring& argument) {
    std::wstring result=L"\"";unsigned slashes=0;
    for (wchar_t ch:argument) {
        if (ch==L'\\') { ++slashes; continue; }
        if (ch==L'\"') { result.append(slashes*2+1,L'\\');result+=ch; }
        else { result.append(slashes,L'\\');result+=ch; }
        slashes=0;
    }
    result.append(slashes*2,L'\\');result+=L'\"';return result;
}
int WINAPI wWinMain(HINSTANCE,HINSTANCE,PWSTR,int) {
    std::vector<wchar_t> location(32768);
    DWORD length=GetModuleFileNameW(nullptr,location.data(),static_cast<DWORD>(location.size()));
    if (!length || length>=location.size()) return 1;
    std::wstring base=parent(std::wstring(location.data(),length));
    bool found=false;
    for (unsigned depth=0;depth<6 && !base.empty();++depth) {
        if (file(base+L"\\.venv\\Scripts\\python.exe") && file(base+L"\\debug_console.py") && file(base+L"\\app.py")) { found=true;break; }
        base=parent(base);
    }
    int count=0;LPWSTR* args=CommandLineToArgvW(GetCommandLineW(),&count);
    const bool check=count==2 && std::wstring(args[1])==L"--check";
    if (!found) {
        if (!check) MessageBoxW(nullptr,L"Keep VietOCR.exe inside VietHandOCR_API_Release\\dist. The existing .venv Python environment is required.",L"VietOCR",MB_OK|MB_ICONERROR);
        LocalFree(args);return 2;
    }
    if (check) { LocalFree(args);return 0; }
    const std::wstring python=base+L"\\.venv\\Scripts\\python.exe";
    std::wstring command=quote(python)+L" -u -X utf8 "+quote(base+L"\\debug_console.py");
    for (int i=1;i<count;++i) command+=L" "+quote(args[i]);
    LocalFree(args);
    STARTUPINFOW startup{};startup.cb=sizeof(startup);
    startup.dwFlags=STARTF_USESHOWWINDOW;startup.wShowWindow=SW_SHOWNORMAL;
    PROCESS_INFORMATION process{};
    // The independent supervisor owns the console; GUI/native crashes leave it open.
    if (!CreateProcessW(python.c_str(),command.data(),nullptr,nullptr,FALSE,CREATE_NEW_CONSOLE,
                        nullptr,base.c_str(),&startup,&process)) {
        MessageBoxW(nullptr,L"Cannot start Python. Try Run-VietOCR.cmd and inspect its error output.",L"VietOCR",MB_OK|MB_ICONERROR);
        return 3;
    }
    CloseHandle(process.hThread);CloseHandle(process.hProcess);return 0;
}
