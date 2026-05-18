#pragma once
#include <cstdint>

#ifdef CTP_BRIDGE_EXPORTS
#define CTP_BRIDGE_API __declspec(dllexport)
#else
#define CTP_BRIDGE_API __declspec(dllimport)
#endif

#define CTP_CALL __stdcall

// Opaque handle types
typedef void* TraderApiHandle;
typedef void* MdApiHandle;

// Callback function pointer types (called from CTP background threads)
extern "C" {

// ==================== Trader API ====================

CTP_BRIDGE_API TraderApiHandle CTP_CALL ctp_trader_create(const char* flow_dir);
CTP_BRIDGE_API void CTP_CALL ctp_trader_destroy(TraderApiHandle handle);

CTP_BRIDGE_API void CTP_CALL ctp_trader_register_front(TraderApiHandle handle, const char* address);
CTP_BRIDGE_API void CTP_CALL ctp_trader_init(TraderApiHandle handle);
CTP_BRIDGE_API int  CTP_CALL ctp_trader_join(TraderApiHandle handle);
CTP_BRIDGE_API void CTP_CALL ctp_trader_release(TraderApiHandle handle);

CTP_BRIDGE_API int  CTP_CALL ctp_trader_req_user_login(
    TraderApiHandle handle, const char* broker_id, const char* user_id,
    const char* password, int req_id);
CTP_BRIDGE_API int  CTP_CALL ctp_trader_req_user_logout(
    TraderApiHandle handle, const char* broker_id, const char* user_id, int req_id);
CTP_BRIDGE_API int  CTP_CALL ctp_trader_req_settlement_info_confirm(
    TraderApiHandle handle, const char* broker_id, const char* investor_id, int req_id);
CTP_BRIDGE_API int  CTP_CALL ctp_trader_req_qry_trading_account(
    TraderApiHandle handle, const char* broker_id, const char* investor_id, int req_id);
CTP_BRIDGE_API int  CTP_CALL ctp_trader_req_qry_investor_position(
    TraderApiHandle handle, const char* broker_id, const char* investor_id,
    const char* instrument_id, int req_id);
CTP_BRIDGE_API int  CTP_CALL ctp_trader_req_qry_instrument(
    TraderApiHandle handle, const char* broker_id, const char* instrument_id, int req_id);

// Order operations - data is passed as raw bytes, struct is defined on Python side
CTP_BRIDGE_API int  CTP_CALL ctp_trader_req_order_insert(
    TraderApiHandle handle, const void* order_field, int req_id);
CTP_BRIDGE_API int  CTP_CALL ctp_trader_req_order_action(
    TraderApiHandle handle, const void* action_field, int req_id);

// ==================== Trader Callback Registration ====================
// Callback type: void(const void* data, const void* error, int req_id, int is_last)
typedef void(CTP_CALL* OnRspLoginCb)(const void* data, const void* error, int req_id, int is_last);
typedef void(CTP_CALL* OnRspSettlementConfirmCb)(const void* data, const void* error, int req_id, int is_last);
typedef void(CTP_CALL* OnRspQryAccountCb)(const void* data, const void* error, int req_id, int is_last);
typedef void(CTP_CALL* OnRspQryPositionCb)(const void* data, const void* error, int req_id, int is_last);
typedef void(CTP_CALL* OnRtnOrderCb)(const void* data);
typedef void(CTP_CALL* OnRtnTradeCb)(const void* data);

// Simple callbacks (no data payload)
typedef void(CTP_CALL* OnFrontConnectedCb)();
typedef void(CTP_CALL* OnFrontDisconnectedCb)(int reason);

CTP_BRIDGE_API void CTP_CALL ctp_trader_set_on_front_connected(TraderApiHandle handle, OnFrontConnectedCb cb);
CTP_BRIDGE_API void CTP_CALL ctp_trader_set_on_front_disconnected(TraderApiHandle handle, OnFrontDisconnectedCb cb);
CTP_BRIDGE_API void CTP_CALL ctp_trader_set_on_rsp_user_login(TraderApiHandle handle, OnRspLoginCb cb);
CTP_BRIDGE_API void CTP_CALL ctp_trader_set_on_rsp_settlement_confirm(TraderApiHandle handle, OnRspSettlementConfirmCb cb);
CTP_BRIDGE_API void CTP_CALL ctp_trader_set_on_rsp_qry_account(TraderApiHandle handle, OnRspQryAccountCb cb);
CTP_BRIDGE_API void CTP_CALL ctp_trader_set_on_rsp_qry_position(TraderApiHandle handle, OnRspQryPositionCb cb);
CTP_BRIDGE_API void CTP_CALL ctp_trader_set_on_rtn_order(TraderApiHandle handle, OnRtnOrderCb cb);
CTP_BRIDGE_API void CTP_CALL ctp_trader_set_on_rtn_trade(TraderApiHandle handle, OnRtnTradeCb cb);

// ==================== MdApi ====================

CTP_BRIDGE_API MdApiHandle CTP_CALL ctp_md_create(const char* flow_dir);
CTP_BRIDGE_API void CTP_CALL ctp_md_destroy(MdApiHandle handle);
CTP_BRIDGE_API void CTP_CALL ctp_md_register_front(MdApiHandle handle, const char* address);
CTP_BRIDGE_API void CTP_CALL ctp_md_init(MdApiHandle handle);
CTP_BRIDGE_API void CTP_CALL ctp_md_release(MdApiHandle handle);
CTP_BRIDGE_API int  CTP_CALL ctp_md_subscribe(MdApiHandle handle, const char* instrument_id);
CTP_BRIDGE_API int  CTP_CALL ctp_md_req_user_login(
    MdApiHandle handle, const char* broker_id, const char* user_id,
    const char* password, int req_id);

// MdApi callbacks
typedef void(CTP_CALL* MdOnFrontConnectedCb)();
typedef void(CTP_CALL* MdOnRspLoginCb)(const void* data, const void* error, int req_id, int is_last);
typedef void(CTP_CALL* MdOnRtnDepthMarketDataCb)(const void* data);

CTP_BRIDGE_API void CTP_CALL ctp_md_set_on_front_connected(MdApiHandle handle, MdOnFrontConnectedCb cb);
CTP_BRIDGE_API void CTP_CALL ctp_md_set_on_rsp_user_login(MdApiHandle handle, MdOnRspLoginCb cb);
CTP_BRIDGE_API void CTP_CALL ctp_md_set_on_rtn_depth_market_data(MdApiHandle handle, MdOnRtnDepthMarketDataCb cb);

// ==================== Utility ====================

CTP_BRIDGE_API const char* CTP_CALL ctp_get_api_version();

} // extern "C"
