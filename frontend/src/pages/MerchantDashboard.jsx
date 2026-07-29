import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import {
  LayoutDashboard,
  Package,
  Ticket,
  ShoppingCart,
  CircleCheck,
  LogOut,
} from "lucide-react";
import OrderList from "../components/merchant/OrderList";
import InventoryPanel from "../components/merchant/InventoryPanel";
import CouponPanel from "../components/merchant/CouponPanel";
import ManualOrderForm from "../components/merchant/ManualOrderForm";

const TABS = [
  { id: "orders", label: "訂單看板", icon: LayoutDashboard },
  { id: "inventory", label: "庫存查詢", icon: Package },
  { id: "coupons", label: "優惠券管理", icon: Ticket },
  { id: "pos", label: "手動建單 (POS)", icon: ShoppingCart },
];

function MerchantDashboard() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState("orders");
  const [inventoryItems, setInventoryItems] = useState([]);
  const [inventoryLoading, setInventoryLoading] = useState(true);
  const [inventoryError, setInventoryError] = useState(null);
  const [inventoryUpdatedAt, setInventoryUpdatedAt] = useState(null);
  const [posSuccessMessage, setPosSuccessMessage] = useState(null);

  const handleAuthError = useCallback(() => {
    navigate("/auth", { state: { from: "/merchant" } });
  }, [navigate]);

  const handleLogout = async () => {
    try {
      await axios.post("/api/auth/logout");
    } catch (err) {
      // 忽略登出 API 失敗（例如 Token 已過期或網路異常），仍繼續清除本地登入狀態
    } finally {
      localStorage.removeItem("token");
      navigate("/auth", { state: { from: "/merchant" } });
    }
  };

  // 庫存資料在頂層共用：庫存查詢頁籤與手動建單 (POS) 頁籤都需要同一份餐點清單，
  // 提到共同的祖先元件才能避免切換頁籤時重複打 API，POS 也才能立刻拿到最新庫存。
  const fetchInventory = useCallback(async () => {
    try {
      const res = await axios.get("/api/inventory");
      setInventoryItems(res.data.items ?? []);
      setInventoryError(null);
      setInventoryUpdatedAt(new Date());
    } catch (err) {
      if (err.response?.status === 401) {
        handleAuthError();
        return;
      }
      setInventoryError(err.response?.data?.message ?? "無法取得庫存資料，請稍後再試");
    } finally {
      setInventoryLoading(false);
    }
  }, [handleAuthError]);

  useEffect(() => {
    if (!localStorage.getItem("token")) {
      handleAuthError();
      return;
    }
    fetchInventory();
  }, [handleAuthError, fetchInventory]);

  const handlePosOrderCreated = () => {
    fetchInventory();
    setActiveTab("orders");
    setPosSuccessMessage("訂單建立成功！");
    setTimeout(() => setPosSuccessMessage(null), 3000);
  };

  return (
    <div className="min-h-screen bg-gray-900">
      <header className="sticky top-0 z-30 border-b border-gray-800 bg-gray-900/95 px-6 py-5 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-start justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold text-white">商家後台管理系統</h1>

            <nav className="mt-5 flex flex-wrap gap-3">
              {TABS.map((tab) => {
                const Icon = tab.icon;
                const isActive = activeTab === tab.id;
                return (
                  <button
                    key={tab.id}
                    type="button"
                    onClick={() => setActiveTab(tab.id)}
                    className={`flex min-h-[52px] items-center gap-2 rounded-xl px-6 text-lg font-bold transition-colors ${
                      isActive
                        ? "bg-amber-500 text-gray-900 shadow"
                        : "border border-gray-700 text-gray-300 hover:bg-gray-800"
                    }`}
                  >
                    <Icon size={22} aria-hidden="true" />
                    {tab.label}
                  </button>
                );
              })}
            </nav>
          </div>

          <button
            type="button"
            onClick={handleLogout}
            className="flex min-h-[52px] items-center gap-2 rounded-xl border border-gray-700 px-6 text-lg font-bold text-gray-300 transition-colors hover:bg-gray-800"
          >
            <LogOut size={22} aria-hidden="true" />
            登出
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-6 py-8">
        {activeTab === "orders" && (
          <OrderList onAuthError={handleAuthError} />
        )}
        {activeTab === "inventory" && (
          <InventoryPanel
            items={inventoryItems}
            isLoading={inventoryLoading}
            error={inventoryError}
            lastUpdatedAt={inventoryUpdatedAt}
            onRefresh={fetchInventory}
            onAuthError={handleAuthError}
          />
        )}
        {activeTab === "coupons" && (
          <CouponPanel onAuthError={handleAuthError} />
        )}
        {activeTab === "pos" && (
          <ManualOrderForm
            inventoryItems={inventoryItems}
            onAuthError={handleAuthError}
            onOrderCreated={handlePosOrderCreated}
          />
        )}
      </main>

      {posSuccessMessage && (
        <div className="fixed bottom-6 right-6 z-50 flex items-center gap-3 rounded-xl bg-emerald-600 px-6 py-4 text-lg font-bold text-white shadow-2xl">
          <CircleCheck size={24} aria-hidden="true" />
          {posSuccessMessage}
        </div>
      )}
    </div>
  );
}

export default MerchantDashboard;
