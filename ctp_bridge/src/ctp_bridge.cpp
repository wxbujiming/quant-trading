#define CTP_BRIDGE_EXPORTS
#include "ctp_bridge.h"
#include <cstring>
#include <string>
#include <new>

// Minimal Windows API declarations (avoid dependency on Windows SDK)
extern "C" {
    __declspec(dllimport) void* __stdcall LoadLibraryA(const char*);
    __declspec(dllimport) int __stdcall FreeLibrary(void*);
    __declspec(dllimport) void* __stdcall GetProcAddress(void*, const char*);
    __declspec(dllimport) unsigned long __stdcall GetModuleFileNameA(void*, char*, unsigned long);
    __declspec(dllimport) unsigned long __stdcall GetCurrentDirectoryA(unsigned long, char*);
    __declspec(dllimport) void* __stdcall GetModuleHandleA(const char*);
}

typedef void* HMODULE;
typedef unsigned long DWORD;
#define MAX_PATH 260

// CTP API headers from vnpy_ctp source
#include "ThostFtdcTraderApi.h"
#include "ThostFtdcMdApi.h"

// ==================== Helpers ====================

static HMODULE g_trader_dll = nullptr;
static HMODULE g_md_dll = nullptr;

typedef CThostFtdcTraderApi* (__stdcall* CreateTraderApiFunc)(const char*);
typedef const char* (__stdcall* GetApiVersionFunc)();
typedef CThostFtdcMdApi* (__stdcall* CreateMdApiFunc)(const char*, bool, bool);

static CreateTraderApiFunc g_create_trader = nullptr;
static CreateMdApiFunc g_create_md = nullptr;
static GetApiVersionFunc g_get_version = nullptr;

static bool g_dll_loaded = false;

// __ImageBase is provided by the linker — its address is the DLL's HMODULE
extern "C" void* __ImageBase;

static void get_dll_dir(char* buf, size_t bufsize) {
    HMODULE module = reinterpret_cast<HMODULE>(&__ImageBase);
    DWORD ret = GetModuleFileNameA(module, buf, static_cast<DWORD>(bufsize));
    if (ret == 0 || ret == bufsize) {
        // Fallback: use current directory
        GetCurrentDirectoryA(static_cast<DWORD>(bufsize), buf);
    }
    char* p = strrchr(buf, '\\');
    if (p) *p = '\0';
}

static bool ensure_dlls_loaded() {
    if (g_dll_loaded) return true;

    // Get the directory of this bridge DLL
    char dll_path[MAX_PATH];
    get_dll_dir(dll_path, sizeof(dll_path));

    std::string dir(dll_path);
    std::string trader_dll_path = dir + "\\thosttraderapi_se.dll";
    std::string md_dll_path = dir + "\\thostmduserapi_se.dll";

    g_trader_dll = LoadLibraryA(trader_dll_path.c_str());
    if (!g_trader_dll) {
        // Try in the Python venv site-packages (project root/.venv/...)
        std::string alt_path = dir + "\\..\\..\\..\\..\\.venv\\Lib\\site-packages\\vnpy_ctp\\api\\thosttraderapi_se.dll";
        g_trader_dll = LoadLibraryA(alt_path.c_str());
    }
    if (!g_trader_dll) {
        // Try in vnpy_ctp api dir relative to project root
        g_trader_dll = LoadLibraryA(
            "D:\\python\\quant-trading\\.venv\\Lib\\site-packages\\vnpy_ctp\\api\\thosttraderapi_se.dll");
    }
    if (!g_trader_dll) {
        // Last resort: current working directory
        g_trader_dll = LoadLibraryA("thosttraderapi_se.dll");
    }

    if (!g_trader_dll) return false;

    g_md_dll = LoadLibraryA(md_dll_path.c_str());
    if (!g_md_dll) {
        g_md_dll = LoadLibraryA("thostmduserapi_se.dll");
    }

    // Resolve factory functions by mangled name
    g_create_trader = (CreateTraderApiFunc)GetProcAddress(
        g_trader_dll,
        "?CreateFtdcTraderApi@CThostFtdcTraderApi@@SAPEAV1@PEBD@Z"
    );
    g_get_version = (GetApiVersionFunc)GetProcAddress(
        g_trader_dll,
        "?GetApiVersion@CThostFtdcTraderApi@@SAPEBDXZ"
    );

    if (g_md_dll) {
        g_create_md = (CreateMdApiFunc)GetProcAddress(
            g_md_dll,
            "?CreateFtdcMdApi@CThostFtdcMdApi@@SAPEAV1@PEBD_N_N@Z"
        );
    }

    if (!g_create_trader) return false;
    g_dll_loaded = true;
    return true;
}

// ==================== SPI Handler (Trader) ====================

class TraderSpiHandler : public CThostFtdcTraderSpi {
public:
    // Callback function pointers (set from Python via ctypes)
    OnFrontConnectedCb         cb_front_connected{ nullptr };
    OnFrontDisconnectedCb      cb_front_disconnected{ nullptr };
    OnRspLoginCb               cb_rsp_user_login{ nullptr };
    OnRspSettlementConfirmCb   cb_rsp_settlement_confirm{ nullptr };
    OnRspQryAccountCb          cb_rsp_qry_account{ nullptr };
    OnRspQryPositionCb         cb_rsp_qry_position{ nullptr };
    OnRtnOrderCb               cb_rtn_order{ nullptr };
    OnRtnTradeCb               cb_rtn_trade{ nullptr };

    // Override virtual methods
    void OnFrontConnected() override {
        if (cb_front_connected) cb_front_connected();
    }

    void OnFrontDisconnected(int nReason) override {
        if (cb_front_disconnected) cb_front_disconnected(nReason);
    }

    void OnRspUserLogin(CThostFtdcRspUserLoginField* pData,
        CThostFtdcRspInfoField* pInfo, int nReqID, bool bIsLast) override {
        if (cb_rsp_user_login) cb_rsp_user_login(pData, pInfo, nReqID, bIsLast ? 1 : 0);
    }

    void OnRspSettlementInfoConfirm(CThostFtdcSettlementInfoConfirmField* pData,
        CThostFtdcRspInfoField* pInfo, int nReqID, bool bIsLast) override {
        if (cb_rsp_settlement_confirm) cb_rsp_settlement_confirm(pData, pInfo, nReqID, bIsLast ? 1 : 0);
    }

    void OnRspQryTradingAccount(CThostFtdcTradingAccountField* pData,
        CThostFtdcRspInfoField* pInfo, int nReqID, bool bIsLast) override {
        if (cb_rsp_qry_account) cb_rsp_qry_account(pData, pInfo, nReqID, bIsLast ? 1 : 0);
    }

    void OnRspQryInvestorPosition(CThostFtdcInvestorPositionField* pData,
        CThostFtdcRspInfoField* pInfo, int nReqID, bool bIsLast) override {
        if (cb_rsp_qry_position) cb_rsp_qry_position(pData, pInfo, nReqID, bIsLast ? 1 : 0);
    }

    void OnRtnOrder(CThostFtdcOrderField* pData) override {
        if (cb_rtn_order) cb_rtn_order(pData);
    }

    void OnRtnTrade(CThostFtdcTradeField* pData) override {
        if (cb_rtn_trade) cb_rtn_trade(pData);
    }
};

// ==================== SPI Handler (Market Data) ====================

class MdSpiHandler : public CThostFtdcMdSpi {
public:
    MdOnFrontConnectedCb        cb_front_connected{ nullptr };
    MdOnRspLoginCb              cb_rsp_user_login{ nullptr };
    MdOnRtnDepthMarketDataCb    cb_rtn_depth_market_data{ nullptr };

    void OnFrontConnected() override {
        if (cb_front_connected) cb_front_connected();
    }

    void OnRspUserLogin(CThostFtdcRspUserLoginField* pData,
        CThostFtdcRspInfoField* pInfo, int nReqID, bool bIsLast) override {
        if (cb_rsp_user_login) cb_rsp_user_login(pData, pInfo, nReqID, bIsLast ? 1 : 0);
    }

    void OnRtnDepthMarketData(CThostFtdcDepthMarketDataField* pData) override {
        if (cb_rtn_depth_market_data) cb_rtn_depth_market_data(pData);
    }
};

// ==================== Wrapper structs ====================

struct TraderApiWrapper {
    CThostFtdcTraderApi* api;
    TraderSpiHandler* spi;
    std::string flow_dir;

    TraderApiWrapper(CThostFtdcTraderApi* a, const std::string& fd)
        : api(a), spi(new TraderSpiHandler()), flow_dir(fd) {
        api->RegisterSpi(spi);
    }

    ~TraderApiWrapper() {
        if (spi) {
            spi->cb_front_connected = nullptr;
            spi->cb_front_disconnected = nullptr;
            spi->cb_rsp_user_login = nullptr;
            spi->cb_rsp_settlement_confirm = nullptr;
            spi->cb_rsp_qry_account = nullptr;
            spi->cb_rsp_qry_position = nullptr;
            spi->cb_rtn_order = nullptr;
            spi->cb_rtn_trade = nullptr;
        }
        if (api) {
            api->Release();
            api = nullptr;
        }
        delete spi;
    }
};

struct MdApiWrapper {
    CThostFtdcMdApi* api;
    MdSpiHandler* spi;
    std::string flow_dir;

    MdApiWrapper(CThostFtdcMdApi* a, const std::string& fd)
        : api(a), spi(new MdSpiHandler()), flow_dir(fd) {
        api->RegisterSpi(spi);
    }

    ~MdApiWrapper() {
        if (spi) {
            spi->cb_front_connected = nullptr;
            spi->cb_rsp_user_login = nullptr;
            spi->cb_rtn_depth_market_data = nullptr;
        }
        if (api) {
            api->Release();
            api = nullptr;
        }
        delete spi;
    }
};

// ==================== Trader API Implementation ====================

TraderApiHandle CTP_CALL ctp_trader_create(const char* flow_dir) {
    if (!ensure_dlls_loaded()) return nullptr;

    std::string fd = flow_dir ? flow_dir : ".";
    CThostFtdcTraderApi* api = g_create_trader(fd.c_str());
    if (!api) return nullptr;

    TraderApiWrapper* wrapper = new(std::nothrow) TraderApiWrapper(api, fd);
    if (!wrapper) {
        api->Release();
        return nullptr;
    }
    return static_cast<TraderApiHandle>(wrapper);
}

void CTP_CALL ctp_trader_destroy(TraderApiHandle handle) {
    if (!handle) return;
    delete static_cast<TraderApiWrapper*>(handle);
}

void CTP_CALL ctp_trader_register_front(TraderApiHandle handle, const char* address) {
    if (!handle || !address) return;
    auto* wrapper = static_cast<TraderApiWrapper*>(handle);
    wrapper->api->RegisterFront(const_cast<char*>(address));
}

void CTP_CALL ctp_trader_init(TraderApiHandle handle) {
    if (!handle) return;
    static_cast<TraderApiWrapper*>(handle)->api->Init();
}

int CTP_CALL ctp_trader_join(TraderApiHandle handle) {
    if (!handle) return -1;
    return static_cast<TraderApiWrapper*>(handle)->api->Join();
}

void CTP_CALL ctp_trader_release(TraderApiHandle handle) {
    ctp_trader_destroy(handle);
}

int CTP_CALL ctp_trader_req_user_login(
    TraderApiHandle handle, const char* broker_id, const char* user_id,
    const char* password, int req_id) {
    if (!handle) return -1;
    auto* wrapper = static_cast<TraderApiWrapper*>(handle);

    CThostFtdcReqUserLoginField field = {};
    if (broker_id) strncpy(field.BrokerID, broker_id, sizeof(field.BrokerID));
    if (user_id) strncpy(field.UserID, user_id, sizeof(field.UserID));
    if (password) strncpy(field.Password, password, sizeof(field.Password));

    // Newer API requires system info params - pass empty
    return wrapper->api->ReqUserLogin(&field, req_id, 0, nullptr);
}

int CTP_CALL ctp_trader_req_user_logout(
    TraderApiHandle handle, const char* broker_id, const char* user_id, int req_id) {
    if (!handle) return -1;
    auto* wrapper = static_cast<TraderApiWrapper*>(handle);

    CThostFtdcUserLogoutField field = {};
    if (broker_id) strncpy(field.BrokerID, broker_id, sizeof(field.BrokerID));
    if (user_id) strncpy(field.UserID, user_id, sizeof(field.UserID));

    return wrapper->api->ReqUserLogout(&field, req_id);
}

int CTP_CALL ctp_trader_req_settlement_info_confirm(
    TraderApiHandle handle, const char* broker_id, const char* investor_id, int req_id) {
    if (!handle) return -1;
    auto* wrapper = static_cast<TraderApiWrapper*>(handle);

    CThostFtdcSettlementInfoConfirmField field = {};
    if (broker_id) strncpy(field.BrokerID, broker_id, sizeof(field.BrokerID));
    if (investor_id) strncpy(field.InvestorID, investor_id, sizeof(field.InvestorID));

    return wrapper->api->ReqSettlementInfoConfirm(&field, req_id);
}

int CTP_CALL ctp_trader_req_qry_trading_account(
    TraderApiHandle handle, const char* broker_id, const char* investor_id, int req_id) {
    if (!handle) return -1;
    auto* wrapper = static_cast<TraderApiWrapper*>(handle);

    CThostFtdcQryTradingAccountField field = {};
    if (broker_id) strncpy(field.BrokerID, broker_id, sizeof(field.BrokerID));
    if (investor_id) strncpy(field.InvestorID, investor_id, sizeof(field.InvestorID));

    return wrapper->api->ReqQryTradingAccount(&field, req_id);
}

int CTP_CALL ctp_trader_req_qry_investor_position(
    TraderApiHandle handle, const char* broker_id, const char* investor_id,
    const char* instrument_id, int req_id) {
    if (!handle) return -1;
    auto* wrapper = static_cast<TraderApiWrapper*>(handle);

    CThostFtdcQryInvestorPositionField field = {};
    if (broker_id) strncpy(field.BrokerID, broker_id, sizeof(field.BrokerID));
    if (investor_id) strncpy(field.InvestorID, investor_id, sizeof(field.InvestorID));
    if (instrument_id) strncpy(field.InstrumentID, instrument_id, sizeof(field.InstrumentID));

    return wrapper->api->ReqQryInvestorPosition(&field, req_id);
}

int CTP_CALL ctp_trader_req_qry_instrument(
    TraderApiHandle handle, const char* broker_id, const char* instrument_id, int req_id) {
    if (!handle) return -1;
    auto* wrapper = static_cast<TraderApiWrapper*>(handle);

    CThostFtdcQryInstrumentField field = {};
    if (instrument_id) strncpy(field.InstrumentID, instrument_id, sizeof(field.InstrumentID));

    return wrapper->api->ReqQryInstrument(&field, req_id);
}

int CTP_CALL ctp_trader_req_order_insert(
    TraderApiHandle handle, const void* order_field, int req_id) {
    if (!handle || !order_field) return -1;
    auto* wrapper = static_cast<TraderApiWrapper*>(handle);
    const auto* field = static_cast<const CThostFtdcInputOrderField*>(order_field);
    return wrapper->api->ReqOrderInsert(const_cast<CThostFtdcInputOrderField*>(field), req_id);
}

int CTP_CALL ctp_trader_req_order_action(
    TraderApiHandle handle, const void* action_field, int req_id) {
    if (!handle || !action_field) return -1;
    auto* wrapper = static_cast<TraderApiWrapper*>(handle);
    const auto* field = static_cast<const CThostFtdcInputOrderActionField*>(action_field);
    return wrapper->api->ReqOrderAction(const_cast<CThostFtdcInputOrderActionField*>(field), req_id);
}

// ==================== Callback setters (Trader) ====================

void CTP_CALL ctp_trader_set_on_front_connected(TraderApiHandle handle, OnFrontConnectedCb cb) {
    if (!handle) return;
    static_cast<TraderApiWrapper*>(handle)->spi->cb_front_connected = cb;
}
void CTP_CALL ctp_trader_set_on_front_disconnected(TraderApiHandle handle, OnFrontDisconnectedCb cb) {
    if (!handle) return;
    static_cast<TraderApiWrapper*>(handle)->spi->cb_front_disconnected = cb;
}
void CTP_CALL ctp_trader_set_on_rsp_user_login(TraderApiHandle handle, OnRspLoginCb cb) {
    if (!handle) return;
    static_cast<TraderApiWrapper*>(handle)->spi->cb_rsp_user_login = cb;
}
void CTP_CALL ctp_trader_set_on_rsp_settlement_confirm(TraderApiHandle handle, OnRspSettlementConfirmCb cb) {
    if (!handle) return;
    static_cast<TraderApiWrapper*>(handle)->spi->cb_rsp_settlement_confirm = cb;
}
void CTP_CALL ctp_trader_set_on_rsp_qry_account(TraderApiHandle handle, OnRspQryAccountCb cb) {
    if (!handle) return;
    static_cast<TraderApiWrapper*>(handle)->spi->cb_rsp_qry_account = cb;
}
void CTP_CALL ctp_trader_set_on_rsp_qry_position(TraderApiHandle handle, OnRspQryPositionCb cb) {
    if (!handle) return;
    static_cast<TraderApiWrapper*>(handle)->spi->cb_rsp_qry_position = cb;
}
void CTP_CALL ctp_trader_set_on_rtn_order(TraderApiHandle handle, OnRtnOrderCb cb) {
    if (!handle) return;
    static_cast<TraderApiWrapper*>(handle)->spi->cb_rtn_order = cb;
}
void CTP_CALL ctp_trader_set_on_rtn_trade(TraderApiHandle handle, OnRtnTradeCb cb) {
    if (!handle) return;
    static_cast<TraderApiWrapper*>(handle)->spi->cb_rtn_trade = cb;
}

// ==================== MdApi Implementation ====================

MdApiHandle CTP_CALL ctp_md_create(const char* flow_dir) {
    if (!ensure_dlls_loaded() || !g_create_md) return nullptr;

    std::string fd = flow_dir ? flow_dir : ".";
    CThostFtdcMdApi* api = g_create_md(fd.c_str(), false, false);
    if (!api) return nullptr;

    MdApiWrapper* wrapper = new(std::nothrow) MdApiWrapper(api, fd);
    if (!wrapper) {
        api->Release();
        return nullptr;
    }
    return static_cast<MdApiHandle>(wrapper);
}

void CTP_CALL ctp_md_destroy(MdApiHandle handle) {
    if (!handle) return;
    delete static_cast<MdApiWrapper*>(handle);
}

void CTP_CALL ctp_md_register_front(MdApiHandle handle, const char* address) {
    if (!handle || !address) return;
    auto* wrapper = static_cast<MdApiWrapper*>(handle);
    wrapper->api->RegisterFront(const_cast<char*>(address));
}

void CTP_CALL ctp_md_init(MdApiHandle handle) {
    if (!handle) return;
    static_cast<MdApiWrapper*>(handle)->api->Init();
}

void CTP_CALL ctp_md_release(MdApiHandle handle) {
    ctp_md_destroy(handle);
}

int CTP_CALL ctp_md_subscribe(MdApiHandle handle, const char* instrument_id) {
    if (!handle || !instrument_id) return -1;
    auto* wrapper = static_cast<MdApiWrapper*>(handle);
    char* ids[] = { const_cast<char*>(instrument_id) };
    return wrapper->api->SubscribeMarketData(ids, 1);
}

int CTP_CALL ctp_md_req_user_login(
    MdApiHandle handle, const char* broker_id, const char* user_id,
    const char* password, int req_id) {
    if (!handle) return -1;
    auto* wrapper = static_cast<MdApiWrapper*>(handle);

    CThostFtdcReqUserLoginField field = {};
    if (broker_id) strncpy(field.BrokerID, broker_id, sizeof(field.BrokerID));
    if (user_id) strncpy(field.UserID, user_id, sizeof(field.UserID));
    if (password) strncpy(field.Password, password, sizeof(field.Password));

    return wrapper->api->ReqUserLogin(&field, req_id);
}

// ==================== Callback setters (Md) ====================

void CTP_CALL ctp_md_set_on_front_connected(MdApiHandle handle, MdOnFrontConnectedCb cb) {
    if (!handle) return;
    static_cast<MdApiWrapper*>(handle)->spi->cb_front_connected = cb;
}
void CTP_CALL ctp_md_set_on_rsp_user_login(MdApiHandle handle, MdOnRspLoginCb cb) {
    if (!handle) return;
    static_cast<MdApiWrapper*>(handle)->spi->cb_rsp_user_login = cb;
}
void CTP_CALL ctp_md_set_on_rtn_depth_market_data(MdApiHandle handle, MdOnRtnDepthMarketDataCb cb) {
    if (!handle) return;
    static_cast<MdApiWrapper*>(handle)->spi->cb_rtn_depth_market_data = cb;
}

// ==================== Utility ====================

const char* CTP_CALL ctp_get_api_version() {
    if (!ensure_dlls_loaded() || !g_get_version) return "unknown";
    return g_get_version();
}
