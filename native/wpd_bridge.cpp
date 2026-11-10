// Windows Portable Devices bridge. Only reads and a bounded preset-bank selector.
// No general property writer, capture, delete, firmware or backup-restore operation.
#define NOMINMAX
#include <windows.h>
#include <initguid.h>
#include <PortableDeviceApi.h>
#include <PortableDeviceTypes.h>
#include <PortableDevice.h>
#include <WpdMtpExtensions.h>
#include <wrl/client.h>
#include <algorithm>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

using Microsoft::WRL::ComPtr;

std::string hex(unsigned long value) {
    std::ostringstream out; out << "0x" << std::hex << std::uppercase << value; return out.str();
}
void check(HRESULT hr, const char* operation) {
    if (FAILED(hr)) throw std::runtime_error(std::string(operation) + " failed (" + hex(hr) + ")");
}
std::string utf8(const std::wstring& text) {
    if (text.empty()) return {};
    int size = WideCharToMultiByte(CP_UTF8, 0, text.data(), (int)text.size(), nullptr, 0, nullptr, nullptr);
    std::string result(size, '\0');
    WideCharToMultiByte(CP_UTF8, 0, text.data(), (int)text.size(), result.data(), size, nullptr, nullptr);
    return result;
}
std::string quote(const std::string& text) {
    std::ostringstream out; out << '"';
    for (unsigned char c : text) {
        if (c == '"' || c == '\\') out << '\\' << c;
        else if (c < 32) { const char* h="0123456789abcdef"; out << "\\u00" << h[c >> 4] << h[c & 15]; }
        else out << c;
    }
    out << '"'; return out.str();
}
ComPtr<IPortableDeviceValues> values() {
    ComPtr<IPortableDeviceValues> result;
    check(CoCreateInstance(CLSID_PortableDeviceValues, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&result)), "Create values");
    return result;
}
PROPERTYKEY vendor_key(unsigned code) {
    return PROPERTYKEY{WPD_PROPERTIES_MTP_VENDOR_EXTENDED_DEVICE_PROPS, code};
}
std::string variant_json(const PROPVARIANT& v) {
    switch (v.vt) {
    case VT_I1: return std::to_string(v.cVal);
    case VT_UI1: return std::to_string(v.bVal);
    case VT_I2: return std::to_string(v.iVal);
    case VT_UI2: return std::to_string(v.uiVal);
    case VT_I4: return std::to_string(v.lVal);
    case VT_UI4: return std::to_string(v.ulVal);
    case VT_I8: return std::to_string(v.hVal.QuadPart);
    case VT_UI8: return std::to_string(v.uhVal.QuadPart);
    case VT_LPWSTR: return quote(utf8(v.pwszVal ? v.pwszVal : L""));
    case VT_BSTR: return quote(utf8(v.bstrVal ? v.bstrVal : L""));
    case VT_BOOL: return v.boolVal ? "true" : "false";
    case VT_ERROR: throw std::runtime_error("Camera property unavailable (" + hex(v.scode) + ")");
    default: throw std::runtime_error("Unsupported WPD value type " + std::to_string(v.vt));
    }
}

class Bridge {
    ComPtr<IPortableDevice> device;
    ComPtr<IPortableDeviceContent> content;
    ComPtr<IPortableDeviceProperties> properties;
    unsigned original_slot=0;
    bool restore_pending=false;
    ComPtr<IPortableDeviceValues> command(PROPERTYKEY key) {
        auto params=values();
        check(params->SetGuidValue(WPD_PROPERTY_COMMON_COMMAND_CATEGORY, key.fmtid), "Command category");
        check(params->SetUnsignedIntegerValue(WPD_PROPERTY_COMMON_COMMAND_ID, key.pid), "Command id");
        return params;
    }
    ComPtr<IPortableDeviceValues> send(IPortableDeviceValues* params) {
        ComPtr<IPortableDeviceValues> result;
        check(device->SendCommand(0, params, &result), "Send MTP command");
        HRESULT status=E_FAIL;
        check(result->GetErrorValue(WPD_PROPERTY_COMMON_HRESULT, &status), "MTP driver result");
        check(status, "MTP driver");
        return result;
    }
    ComPtr<IPortableDeviceValues> operation(PROPERTYKEY phase, unsigned opcode, std::vector<unsigned> arguments) {
        auto params=command(phase);
        check(params->SetUnsignedIntegerValue(WPD_PROPERTY_MTP_EXT_OPERATION_CODE, opcode), "PTP operation code");
        ComPtr<IPortableDevicePropVariantCollection> collection;
        check(CoCreateInstance(CLSID_PortableDevicePropVariantCollection, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&collection)), "Create MTP parameters");
        for(unsigned arg : arguments) {
            PROPVARIANT v; PropVariantInit(&v); v.vt=VT_UI4; v.ulVal=arg;
            check(collection->Add(&v), "Add MTP parameter");
        }
        check(params->SetIPortableDevicePropVariantCollectionValue(WPD_PROPERTY_MTP_EXT_OPERATION_PARAMS, collection.Get()), "Set MTP parameters");
        return params;
    }
    void finish(const std::wstring& context) {
        auto params=command(WPD_COMMAND_MTP_EXT_END_DATA_TRANSFER);
        check(params->SetStringValue(WPD_PROPERTY_MTP_EXT_TRANSFER_CONTEXT, context.c_str()), "End context");
        auto result=send(params.Get());
        DWORD code=0; check(result->GetUnsignedIntegerValue(WPD_PROPERTY_MTP_EXT_RESPONSE_CODE, &code), "PTP response");
        if(code!=0x2001) throw std::runtime_error("Camera PTP response " + hex(code));
    }
    std::wstring context_of(IPortableDeviceValues* result) {
        PWSTR raw=nullptr;
        check(result->GetStringValue(WPD_PROPERTY_MTP_EXT_TRANSFER_CONTEXT, &raw), "MTP transfer context");
        std::wstring context=raw; CoTaskMemFree(raw); return context;
    }
    std::vector<BYTE> read_ptp(unsigned opcode, std::vector<unsigned> arguments) {
        auto params=operation(WPD_COMMAND_MTP_EXT_EXECUTE_COMMAND_WITH_DATA_TO_READ, opcode, arguments);
        auto start=send(params.Get());
        std::wstring context=context_of(start.Get());
        std::vector<BYTE> bytes;
        bool ending=false;
        try {
            ULONGLONG total=0;
            check(start->GetUnsignedLargeIntegerValue(WPD_PROPERTY_MTP_EXT_TRANSFER_TOTAL_DATA_SIZE, &total), "PTP read size");
            if(total>65536) throw std::runtime_error("PTP response exceeds the 64 KiB recipe-reader limit");
            while(bytes.size()<total) {
                DWORD wanted=(DWORD)std::min<ULONGLONG>(4096,total-bytes.size());
                auto request=command(WPD_COMMAND_MTP_EXT_READ_DATA);
                check(request->SetStringValue(WPD_PROPERTY_MTP_EXT_TRANSFER_CONTEXT,context.c_str()),"Read context");
                check(request->SetUnsignedIntegerValue(WPD_PROPERTY_MTP_EXT_TRANSFER_NUM_BYTES_TO_READ,wanted),"Read count");
                std::vector<BYTE> buffer(wanted,0);
                check(request->SetBufferValue(WPD_PROPERTY_MTP_EXT_TRANSFER_DATA,buffer.data(),wanted),"Read buffer");
                auto result=send(request.Get());
                DWORD received=0; check(result->GetUnsignedIntegerValue(WPD_PROPERTY_MTP_EXT_TRANSFER_NUM_BYTES_READ,&received),"Received count");
                BYTE* data=nullptr; DWORD size=0;
                check(result->GetBufferValue(WPD_PROPERTY_MTP_EXT_TRANSFER_DATA,&data,&size),"Received buffer");
                if(!received || received>size || received>wanted) { CoTaskMemFree(data); throw std::runtime_error("Invalid or incomplete PTP read"); }
                bytes.insert(bytes.end(),data,data+received); CoTaskMemFree(data);
            }
            ending=true; finish(context);
        } catch(...) { if(!ending) { try { finish(context); } catch(...) {} } throw; }
        return bytes;
    }
    static std::string bytes_json(const std::vector<BYTE>& bytes) {
        const char* h="0123456789abcdef";
        std::string text; for(BYTE b:bytes) { text+=h[b>>4]; text+=h[b&15]; }
        return "{\"hex\":" + quote(text) + "}";
    }
public:
    ~Bridge() {
        if (restore_pending) {
            try { restore(); }
            catch(const std::exception& exc) { std::cerr << "Bank selector restoration failed: " << exc.what() << std::endl; }
        }
        if (device) device->Close();
    }
    static std::vector<std::wstring> devices() {
        ComPtr<IPortableDeviceManager> manager;
        check(CoCreateInstance(CLSID_PortableDeviceManager, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&manager)), "Create WPD manager");
        DWORD count=0; check(manager->GetDevices(nullptr, &count), "List WPD devices");
        std::vector<PWSTR> identifiers(count, nullptr);
        DWORD capacity=count;
        if(count) check(manager->GetDevices(identifiers.data(), &count), "Read WPD identifiers");
        if(count>capacity) throw std::runtime_error("Device inventory changed; retry the connection");
        std::vector<std::wstring> found;
        for (DWORD i=0; i<count; ++i) {
            std::wstring id=identifiers[i], upper=id;
            std::transform(upper.begin(), upper.end(), upper.begin(), ::towupper);
            if(upper.find(L"VID_04CB") != std::wstring::npos) found.push_back(id);
            CoTaskMemFree(identifiers[i]);
        }
        return found;
    }
    void open(const std::wstring& id) {
        auto client=values();
        check(client->SetStringValue(WPD_CLIENT_NAME, L"Iro Recipe Reader"), "Client name");
        check(client->SetUnsignedIntegerValue(WPD_CLIENT_MAJOR_VERSION, 0), "Client version");
        check(client->SetUnsignedIntegerValue(WPD_CLIENT_MINOR_VERSION, 3), "Client version");
        check(client->SetUnsignedIntegerValue(WPD_CLIENT_SECURITY_QUALITY_OF_SERVICE, SECURITY_IMPERSONATION), "Client security");
        check(client->SetUnsignedIntegerValue(WPD_CLIENT_DESIRED_ACCESS, GENERIC_READ | GENERIC_WRITE), "Client access");
        check(CoCreateInstance(CLSID_PortableDeviceFTM, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&device)), "Create WPD device");
        check(device->Open(id.c_str(), client.Get()), "Open camera (close other camera apps and check USB mode)");
        check(device->Content(&content), "Get content interface");
        check(content->Properties(&properties), "Get properties interface");
    }
    std::string read(PROPERTYKEY key) {
        ComPtr<IPortableDeviceKeyCollection> keys;
        check(CoCreateInstance(CLSID_PortableDeviceKeyCollection, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&keys)), "Create keys");
        check(keys->Add(key), "Add key");
        ComPtr<IPortableDeviceValues> result;
        check(properties->GetValues(WPD_DEVICE_OBJECT_ID, keys.Get(), &result), "Read device property");
        PROPVARIANT value; PropVariantInit(&value);
        check(result->GetValue(key, &value), "Get device property result");
        try {
            std::string json="{\"type\":" + std::to_string(value.vt) + ",\"value\":" + variant_json(value) + "}";
            PropVariantClear(&value); return json;
        } catch (...) { PropVariantClear(&value); throw; }
    }
    std::string info() {
        std::string model=read(WPD_DEVICE_MODEL), firmware="null";
        try { firmware=read(WPD_DEVICE_FIRMWARE_VERSION); } catch(...) {}
        ComPtr<IPortableDeviceKeyCollection> keys;
        check(properties->GetSupportedProperties(WPD_DEVICE_OBJECT_ID, &keys), "Get supported device properties");
        DWORD count=0; check(keys->GetCount(&count), "Count properties");
        std::ostringstream ids; ids << '['; bool first=true;
        for (DWORD i=0; i<count; ++i) {
            PROPERTYKEY key; check(keys->GetAt(i, &key), "Read property key");
            if(IsEqualGUID(key.fmtid, WPD_PROPERTIES_MTP_VENDOR_EXTENDED_DEVICE_PROPS)) {
                if(!first) ids << ','; first=false; ids << key.pid;
            }
        }
        ids << ']';
        return "{\"model\":" + model + ",\"firmware\":" + firmware + ",\"properties\":" + ids.str() + "}";
    }
    std::string ptp_info() { return bytes_json(read_ptp(0x1001,{})); }
    std::string describe(unsigned id) {
        if(id<0xD18C || id>0xD1A5) throw std::runtime_error("Only preset descriptors are allowed");
        return bytes_json(read_ptp(0x1014,{id}));
    }
    std::string get_preset(unsigned id) {
        if(id<0xD18C || id>0xD1A5) throw std::runtime_error("Only preset property reads are allowed");
        return bytes_json(read_ptp(0x1015,{id}));
    }
    void select(unsigned slot) {
        if(slot < 1 || slot > 7) throw std::runtime_error("Only bank selector values 1..7 are allowed");
        if(!restore_pending) {
            auto model=read(WPD_DEVICE_MODEL);
            if(model.find("\"X-E5\"")==std::string::npos) throw std::runtime_error("Bank selection is currently enabled only for X-E5");
            auto bytes=read_ptp(0x1015,{0xD18C});
            if(bytes.size()!=2 || bytes[1]!=0 || bytes[0]<1 || bytes[0]>7) throw std::runtime_error("Cannot preserve the camera's original bank selector");
            original_slot=bytes[0]; restore_pending=true;
        }
        auto params=operation(WPD_COMMAND_MTP_EXT_EXECUTE_COMMAND_WITH_DATA_TO_WRITE,0x1016,{0xD18C});
        check(params->SetUnsignedLargeIntegerValue(WPD_PROPERTY_MTP_EXT_TRANSFER_TOTAL_DATA_SIZE,2),"Selector payload size");
        auto start=send(params.Get());
        std::wstring context=context_of(start.Get());
        bool ending=false;
        try {
            auto request=command(WPD_COMMAND_MTP_EXT_WRITE_DATA);
            BYTE bytes[2]={(BYTE)slot,0};
            check(request->SetStringValue(WPD_PROPERTY_MTP_EXT_TRANSFER_CONTEXT,context.c_str()),"Selector context");
            check(request->SetUnsignedIntegerValue(WPD_PROPERTY_MTP_EXT_TRANSFER_NUM_BYTES_TO_WRITE,2),"Selector count");
            check(request->SetBufferValue(WPD_PROPERTY_MTP_EXT_TRANSFER_DATA,bytes,2),"Selector buffer");
            auto result=send(request.Get());
            DWORD written=0; check(result->GetUnsignedIntegerValue(WPD_PROPERTY_MTP_EXT_TRANSFER_NUM_BYTES_WRITTEN,&written),"Selector written count");
            if(written!=2) throw std::runtime_error("Incomplete bank selection");
            ending=true; finish(context);
        } catch(...) { if(!ending) { try { finish(context); } catch(...) {} } throw; }
    }
    void restore() {
        if(!restore_pending) return;
        select(original_slot);
        auto current=read_ptp(0x1015,{0xD18C});
        if(current.size()!=2 || current[0]!=original_slot || current[1]!=0) throw std::runtime_error("Restored bank selector readback mismatch");
        restore_pending=false;
    }
};

class SessionLock {
    HANDLE handle=nullptr;
public:
    SessionLock() {
        handle=CreateMutexW(nullptr,FALSE,L"Local\\IroFujifilmPresetReader");
        if(!handle) throw std::runtime_error("Cannot create camera session lock");
        DWORD result=WaitForSingleObject(handle,0);
        if(result!=WAIT_OBJECT_0 && result!=WAIT_ABANDONED) {
            CloseHandle(handle); handle=nullptr;
            throw std::runtime_error("Another Iro camera connection is active. Wait for it to finish.");
        }
    }
    ~SessionLock() { if(handle) { ReleaseMutex(handle); CloseHandle(handle); } }
};

int wmain(int argc, wchar_t** argv) {
    HRESULT initialized=CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if(FAILED(initialized)) return 2;
    int exit_code=0;
    try {
        auto ids=Bridge::devices();
        if(argc>1 && std::wstring(argv[1]) == L"--list") {
            std::cout << "[";
            for(size_t i=0; i<ids.size(); ++i) { if(i) std::cout << ','; std::cout << quote(utf8(ids[i])); }
            std::cout << "]" << std::endl;
        } else {
            SessionLock session_lock;
            if(ids.empty()) throw std::runtime_error("No Fujifilm WPD camera found. Connect by USB with communication enabled.");
            std::wstring selected;
            if(argc==3 && std::wstring(argv[1])==L"--device-id") selected=argv[2];
            else if(ids.size()==1) selected=ids[0];
            else throw std::runtime_error("Multiple Fujifilm cameras found. Choose an explicit device id.");
            if(std::find(ids.begin(),ids.end(),selected)==ids.end()) throw std::runtime_error("Selected Fujifilm camera is not connected");
            Bridge bridge; bridge.open(selected);
            auto information=bridge.info();
            std::cout << "{\"ok\":true,\"data\":" << information << "}" << std::endl;
            std::string line;
            while(std::getline(std::cin,line)) {
                if(line=="quit") break;
                try {
                    if(line=="info") { auto data=bridge.info(); std::cout << "{\"ok\":true,\"data\":" << data << "}" << std::endl; }
                    else if(line=="ptp-info") { auto data=bridge.ptp_info(); std::cout << "{\"ok\":true,\"data\":" << data << "}" << std::endl; }
                    else if(line=="restore") { bridge.restore(); std::cout << "{\"ok\":true,\"data\":null}" << std::endl; }
                    else if(line.rfind("describe ",0)==0) {
                        size_t consumed=0; unsigned id=std::stoul(line.substr(9),&consumed,16);
                        if(consumed!=line.size()-9) throw std::runtime_error("Invalid descriptor id");
                        auto data=bridge.describe(id); std::cout << "{\"ok\":true,\"data\":" << data << "}" << std::endl;
                    }
                    else if(line.rfind("get ",0)==0) {
                        size_t consumed=0; unsigned id=std::stoul(line.substr(4),&consumed,16);
                        if(consumed != line.size()-4 || id < 0xD18C || id > 0xD1A5) throw std::runtime_error("Only preset property reads D18C..D1A5 are allowed");
                        auto data=bridge.get_preset(id);
                        std::cout << "{\"ok\":true,\"data\":" << data << "}" << std::endl;
                    } else if(line.rfind("select ",0)==0) {
                        size_t consumed=0; unsigned slot=std::stoul(line.substr(7),&consumed,10);
                        if(consumed!=line.size()-7) throw std::runtime_error("Invalid bank selector");
                        bridge.select(slot); std::cout << "{\"ok\":true,\"data\":null}" << std::endl;
                    } else throw std::runtime_error("Unsupported bridge command");
                } catch(const std::exception& exc) { std::cout << "{\"ok\":false,\"error\":" << quote(exc.what()) << "}" << std::endl; }
            }
        }
    } catch(const std::exception& exc) {
        std::cout << "{\"ok\":false,\"error\":" << quote(exc.what()) << "}" << std::endl; exit_code=1;
    }
    CoUninitialize(); return exit_code;
}
