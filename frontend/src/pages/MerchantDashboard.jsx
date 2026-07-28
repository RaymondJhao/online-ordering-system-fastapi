import React, { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import {
  Clock,
  CheckCircle2,
  ChefHat,
  BellRing,
  XCircle,
  Ban,
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Banknote,
  CreditCard,
  LayoutDashboard,
  Package,
  Ticket,
  Plus,
  Minus,
  ShoppingCart,
  Trash2,
  CircleCheck,
  Loader2,
} from "lucide-react";

const PAGE_SIZE = 8;
const AUTO_REFRESH_MS = 10000;

const TABS = [
  { id: "orders", label: "訂單看板", icon: LayoutDashboard },
  { id: "inventory", label: "庫存查詢", icon: Package },
  { id: "coupons", label: "優惠券管理", icon: Ticket },
  { id: "pos", label: "手動建單 (POS)", icon: ShoppingCart },
];

// 狀態外觀設定：色弱友善設計 — 每個狀態都同時有「顏色」+「圖示」+「純文字標籤」，
// 使用者不需要只靠顏色就能分辨狀態。
const STATUS_CONFIG = {
  PENDING: {
    label: "新訂單",
    icon: Clock,
    badge: "bg-amber-100 text-amber-800 border border-amber-300",
    cardAccent: "border-t-8 border-amber-400",
  },
  ACCEPTED: {
    label: "已接單",
    icon: CheckCircle2,
    badge: "bg-blue-100 text-blue-800 border border-blue-300",
    cardAccent: "border-t-8 border-blue-400",
  },
  PREPARING: {
    label: "製作中",
    icon: ChefHat,
    badge: "bg-purple-100 text-purple-800 border border-purple-300",
    cardAccent: "border-t-8 border-purple-400",
  },
  READY: {
    label: "待取餐",
    icon: BellRing,
    badge: "bg-emerald-100 text-emerald-800 border border-emerald-300",
    cardAccent: "border-t-8 border-emerald-400",
  },
};

// 嚴格狀態轉移表（對齊後端 app/routes/order.py 的 ALLOWED_TRANSITIONS）：
// 只有這裡列出的下一步狀態才會顯示對應的操作按鈕。
const ACTIONS_BY_STATUS = {
  PENDING: [
    {
      status: "ACCEPTED",
      label: "接單",
      icon: CheckCircle2,
      className: "bg-emerald-600 hover:bg-emerald-700 text-white",
      destructive: false,
    },
    {
      status: "REJECTED",
      label: "拒絕訂單",
      icon: XCircle,
      className: "bg-red-600 hover:bg-red-700 text-white",
      destructive: true,
    },
  ],
  ACCEPTED: [
    {
      status: "PREPARING",
      label: "開始製作",
      icon: ChefHat,
      className: "bg-purple-600 hover:bg-purple-700 text-white",
      destructive: false,
    },
    {
      status: "CANCELLED",
      label: "取消訂單",
      icon: Ban,
      className: "bg-gray-500 hover:bg-gray-600 text-white",
      destructive: true,
    },
  ],
  PREPARING: [
    {
      status: "READY",
      label: "餐點完成",
      icon: BellRing,
      className: "bg-emerald-600 hover:bg-emerald-700 text-white",
      destructive: false,
    },
    {
      status: "CANCELLED",
      label: "取消訂單",
      icon: Ban,
      className: "bg-gray-500 hover:bg-gray-600 text-white",
      destructive: true,
    },
  ],
  READY: [
    {
      status: "COMPLETED",
      label: "顧客已取餐",
      icon: CheckCircle2,
      className: "bg-emerald-600 hover:bg-emerald-700 text-white",
      destructive: false,
    },
  ],
};

const REJECT_REASON_PRESETS = [
  "太忙，來不及製作",
  "缺料，無法供應",
  "其他原因",
];

// 大螢幕只顯示「還需要人處理」的訂單，COMPLETED / REJECTED / CANCELLED / REFUNDED
// 這些終態訂單不佔用看板版位。
const ACTIVE_STATUSES = new Set(["PENDING", "ACCEPTED", "PREPARING", "READY"]);

const DISCOUNT_TYPE_LABELS = {
  PERCENTAGE: "百分比折扣",
  FIXED: "固定金額折抵",
};

function StatusBadge({ status }) {
  const config = STATUS_CONFIG[status];
  if (!config) return null;
  const Icon = config.icon;

  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full px-4 py-2 text-base font-bold ${config.badge}`}
    >
      <Icon size={22} aria-hidden="true" />
      {config.label}
    </span>
  );
}

function PaymentBadge({ paymentMethod, paymentStatus }) {
  const isCash = paymentMethod === "CASH";
  const Icon = isCash ? Banknote : CreditCard;
  const paid = paymentStatus === "PAID";

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-semibold ${
        isCash
          ? "bg-orange-100 text-orange-800"
          : paid
            ? "bg-gray-100 text-gray-700"
            : "bg-red-100 text-red-700"
      }`}
    >
      <Icon size={16} aria-hidden="true" />
      {isCash ? "現金取餐時收款" : paid ? "已線上付款" : "尚未付款"}
    </span>
  );
}

function RejectReasonModal({ order, isSubmitting, error, onConfirm, onClose }) {
  const [reason, setReason] = useState(REJECT_REASON_PRESETS[0]);
  const [customReason, setCustomReason] = useState("");

  const isCustom = reason === "其他原因";
  const finalReason = isCustom ? customReason.trim() : reason;
  const canConfirm = finalReason.length > 0 && !isSubmitting;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl">
        <div className="flex items-center gap-3 text-red-600">
          <AlertTriangle size={32} aria-hidden="true" />
          <h2 className="text-2xl font-bold">確定要拒絕這筆訂單嗎？</h2>
        </div>

        <p className="mt-3 text-lg text-gray-700">
          訂單編號 <span className="font-bold">#{order.id}</span>
          ，此操作無法復原，請選擇拒單原因：
        </p>

        <div className="mt-4 space-y-3">
          {REJECT_REASON_PRESETS.map((preset) => (
            <label
              key={preset}
              className="flex min-h-[48px] cursor-pointer items-center gap-3 rounded-xl border border-gray-300 px-4 py-3 text-lg has-[:checked]:border-red-500 has-[:checked]:bg-red-50"
            >
              <input
                type="radio"
                name="reject-reason"
                value={preset}
                checked={reason === preset}
                onChange={() => setReason(preset)}
                className="h-5 w-5 accent-red-600"
              />
              {preset}
            </label>
          ))}

          {isCustom && (
            <textarea
              value={customReason}
              onChange={(e) => setCustomReason(e.target.value)}
              placeholder="請輸入拒單原因..."
              rows={3}
              className="w-full rounded-xl border border-gray-300 p-3 text-lg focus:border-red-500 focus:outline-none focus:ring-1 focus:ring-red-500"
            />
          )}
        </div>

        {error && (
          <p className="mt-3 text-base font-medium text-red-600">{error}</p>
        )}

        <div className="mt-6 flex gap-4">
          <button
            type="button"
            onClick={onClose}
            disabled={isSubmitting}
            className="min-h-[48px] flex-1 rounded-xl border border-gray-300 text-lg font-semibold text-gray-700 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => onConfirm(finalReason)}
            disabled={!canConfirm}
            className="min-h-[48px] flex-1 rounded-xl bg-red-600 text-lg font-bold text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:bg-gray-300"
          >
            {isSubmitting ? "處理中..." : "確認拒單"}
          </button>
        </div>
      </div>
    </div>
  );
}

function ConfirmCancelModal({
  order,
  isSubmitting,
  error,
  onConfirm,
  onClose,
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl">
        <div className="flex items-center gap-3 text-red-600">
          <AlertTriangle size={32} aria-hidden="true" />
          <h2 className="text-2xl font-bold">確定要取消這筆訂單嗎？</h2>
        </div>

        <p className="mt-3 text-lg text-gray-700">
          訂單編號 <span className="font-bold">#{order.id}</span>
          ，取消後無法復原，顧客也會收到通知。
        </p>

        {error && (
          <p className="mt-3 text-base font-medium text-red-600">{error}</p>
        )}

        <div className="mt-6 flex gap-4">
          <button
            type="button"
            onClick={onClose}
            disabled={isSubmitting}
            className="min-h-[48px] flex-1 rounded-xl border border-gray-300 text-lg font-semibold text-gray-700 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            返回
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isSubmitting}
            className="min-h-[48px] flex-1 rounded-xl bg-red-600 text-lg font-bold text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:bg-gray-300"
          >
            {isSubmitting ? "處理中..." : "確認取消"}
          </button>
        </div>
      </div>
    </div>
  );
}

function OrderCard({ order, isProcessing, onAction }) {
  const config = STATUS_CONFIG[order.status];
  const actions = ACTIONS_BY_STATUS[order.status] ?? [];

  return (
    <div
      className={`flex flex-col rounded-2xl bg-white shadow-lg ${config?.cardAccent ?? "border-t-8 border-gray-300"}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-3 p-5 pb-3">
        <span className="text-4xl font-bold text-gray-900">#{order.id}</span>
        <StatusBadge status={order.status} />
      </div>

      <div className="flex flex-wrap items-center gap-2 px-5">
        <PaymentBadge
          paymentMethod={order.payment_method}
          paymentStatus={order.payment_status}
        />
        {order.table_number && (
          <span className="rounded-full bg-gray-100 px-3 py-1.5 text-sm font-semibold text-gray-700">
            桌號 {order.table_number}
          </span>
        )}
      </div>

      <ul className="mt-3 flex-1 divide-y divide-gray-100 px-5">
        {order.items.map((item) => (
          <li
            key={item.menu_item_id}
            className="flex items-center justify-between gap-3 py-3"
          >
            <span className="text-2xl font-semibold text-gray-900">
              {item.name}
            </span>
            <span className="whitespace-nowrap text-2xl font-bold text-gray-900">
              x{item.quantity}
            </span>
          </li>
        ))}
      </ul>

      {order.pickup_time && (
        <p className="mx-5 mb-1 text-base text-gray-600">
          預約取餐：
          <span className="font-semibold text-gray-900">
            {new Date(order.pickup_time).toLocaleString("zh-TW", {
              dateStyle: "short",
              timeStyle: "short",
            })}
          </span>
        </p>
      )}

      {order.discount_amount > 0 && (
        <p className="mx-5 mb-1 text-base text-orange-600">
          優惠折抵：- NT$ {order.discount_amount}
        </p>
      )}

      <div className="flex items-center justify-between px-5 py-3 text-lg font-bold text-gray-900">
        <span>總金額</span>
        <span>NT$ {order.total_price}</span>
      </div>

      {order.reject_reason && (
        <p className="mx-5 mb-3 rounded-lg bg-red-50 px-3 py-2 text-base text-red-700">
          拒單原因：{order.reject_reason}
        </p>
      )}

      {actions.length > 0 && (
        <div className="flex flex-wrap gap-4 border-t border-gray-100 p-5">
          {actions.map((action) => {
            const Icon = action.icon;
            return (
              <button
                key={action.status}
                type="button"
                disabled={isProcessing}
                onClick={() => onAction(order, action)}
                className={`flex min-h-[48px] min-w-[48px] flex-1 items-center justify-center gap-2 rounded-xl px-4 text-lg font-bold shadow transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${action.className}`}
              >
                <Icon size={24} aria-hidden="true" />
                {action.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function OrderBoardPanel({ onAuthError }) {
  const [orders, setOrders] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [page, setPage] = useState(0);
  const [processingOrderId, setProcessingOrderId] = useState(null);
  const [pendingAction, setPendingAction] = useState(null); // { order, action }
  const [modalError, setModalError] = useState(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState(null);
  const intervalRef = useRef(null);

  const fetchOrders = useCallback(async () => {
    try {
      const res = await axios.get("/api/orders");
      setOrders(res.data.orders ?? []);
      setError(null);
      setLastUpdatedAt(new Date());
    } catch (err) {
      if (err.response?.status === 401) {
        onAuthError();
        return;
      }
      setError(err.response?.data?.message ?? "無法取得訂單資料，請稍後再試");
    } finally {
      setIsLoading(false);
    }
  }, [onAuthError]);

  useEffect(() => {
    fetchOrders();

    intervalRef.current = setInterval(fetchOrders, AUTO_REFRESH_MS);
    return () => clearInterval(intervalRef.current);
  }, [fetchOrders]);

  const activeOrders = orders
    .filter((order) => ACTIVE_STATUSES.has(order.status))
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

  const pageCount = Math.max(Math.ceil(activeOrders.length / PAGE_SIZE), 1);
  const safePage = Math.min(page, pageCount - 1);
  const pagedOrders = activeOrders.slice(
    safePage * PAGE_SIZE,
    safePage * PAGE_SIZE + PAGE_SIZE,
  );

  const closeModal = () => {
    setPendingAction(null);
    setModalError(null);
  };

  const submitStatusUpdate = async (order, targetStatus, rejectReason) => {
    setProcessingOrderId(order.id);
    setModalError(null);

    try {
      await axios.put(`/api/orders/${order.id}/status`, {
        status: targetStatus,
        ...(rejectReason ? { reject_reason: rejectReason } : {}),
      });
      closeModal();
      await fetchOrders();
    } catch (err) {
      setModalError(
        err.response?.data?.message ?? "更新訂單狀態失敗，請稍後再試",
      );
    } finally {
      setProcessingOrderId(null);
    }
  };

  const handleAction = (order, action) => {
    if (action.destructive) {
      setPendingAction({ order, action });
      return;
    }
    submitStatusUpdate(order, action.status);
  };

  return (
    <>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <p className="text-lg text-gray-300">
          待處理總數：
          <span className="text-2xl font-bold text-amber-400">
            {activeOrders.length}
          </span>{" "}
          筆
        </p>

        <div className="flex items-center gap-4">
          {lastUpdatedAt && (
            <span className="text-sm text-gray-400">
              最後更新：{lastUpdatedAt.toLocaleTimeString("zh-TW")}
            </span>
          )}
          <button
            type="button"
            onClick={fetchOrders}
            className="flex min-h-[48px] min-w-[48px] items-center gap-2 rounded-xl border border-gray-600 px-4 text-lg font-semibold text-white hover:bg-gray-800"
          >
            <RefreshCw size={22} aria-hidden="true" />
            重新整理
          </button>
        </div>
      </div>

      {isLoading && (
        <p className="py-16 text-center text-2xl text-gray-300">
          訂單載入中...
        </p>
      )}

      {!isLoading && error && (
        <p className="py-16 text-center text-2xl text-red-400">{error}</p>
      )}

      {!isLoading && !error && activeOrders.length === 0 && (
        <p className="py-16 text-center text-2xl text-gray-300">
          目前沒有需要處理的訂單
        </p>
      )}

      {!isLoading && !error && activeOrders.length > 0 && (
        <>
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-4">
            {pagedOrders.map((order) => (
              <OrderCard
                key={order.id}
                order={order}
                isProcessing={processingOrderId === order.id}
                onAction={handleAction}
              />
            ))}
          </div>

          {pageCount > 1 && (
            <div className="mt-8 flex items-center justify-center gap-4">
              <button
                type="button"
                onClick={() => setPage((p) => Math.max(p - 1, 0))}
                disabled={safePage === 0}
                className="flex min-h-[48px] min-w-[48px] items-center gap-2 rounded-xl border border-gray-600 px-4 text-lg font-semibold text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-40"
              >
                <ChevronLeft size={24} aria-hidden="true" />
                上一頁
              </button>
              <span className="text-lg font-semibold text-gray-300">
                第 {safePage + 1} / {pageCount} 頁
              </span>
              <button
                type="button"
                onClick={() => setPage((p) => Math.min(p + 1, pageCount - 1))}
                disabled={safePage >= pageCount - 1}
                className="flex min-h-[48px] min-w-[48px] items-center gap-2 rounded-xl border border-gray-600 px-4 text-lg font-semibold text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-40"
              >
                下一頁
                <ChevronRight size={24} aria-hidden="true" />
              </button>
            </div>
          )}
        </>
      )}

      {pendingAction?.action.status === "REJECTED" && (
        <RejectReasonModal
          order={pendingAction.order}
          isSubmitting={processingOrderId === pendingAction.order.id}
          error={modalError}
          onClose={closeModal}
          onConfirm={(reason) =>
            submitStatusUpdate(pendingAction.order, "REJECTED", reason)
          }
        />
      )}

      {pendingAction?.action.status === "CANCELLED" && (
        <ConfirmCancelModal
          order={pendingAction.order}
          isSubmitting={processingOrderId === pendingAction.order.id}
          error={modalError}
          onClose={closeModal}
          onConfirm={() => submitStatusUpdate(pendingAction.order, "CANCELLED")}
        />
      )}
    </>
  );
}

function AddMenuItemModal({ isSubmitting, error, onConfirm, onClose }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [price, setPrice] = useState("");

  const canSubmit = name.trim().length > 0 && Number(price) > 0 && !isSubmitting;

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!canSubmit) return;
    onConfirm({
      name: name.trim(),
      description: description.trim(),
      price: Number(price),
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl">
        <h2 className="text-2xl font-bold text-gray-900">＋ 新增餐點</h2>

        <form onSubmit={handleSubmit} className="mt-5 space-y-4">
          <div>
            <label className="mb-2 block text-sm font-semibold text-gray-700">
              餐點名稱
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="例：珍珠奶茶"
              autoFocus
              className="min-h-[48px] w-full rounded-xl border border-gray-300 px-4 text-lg focus:border-amber-500 focus:outline-none focus:ring-1 focus:ring-amber-500"
            />
          </div>

          <div>
            <label className="mb-2 block text-sm font-semibold text-gray-700">
              描述
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="選填，例：招牌配方，甜度冰塊皆可調整"
              rows={3}
              className="w-full rounded-xl border border-gray-300 p-3 text-lg focus:border-amber-500 focus:outline-none focus:ring-1 focus:ring-amber-500"
            />
          </div>

          <div>
            <label className="mb-2 block text-sm font-semibold text-gray-700">
              價格（NT$）
            </label>
            <input
              type="number"
              min="1"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              placeholder="例：50"
              className="min-h-[48px] w-full rounded-xl border border-gray-300 px-4 text-lg focus:border-amber-500 focus:outline-none focus:ring-1 focus:ring-amber-500"
            />
          </div>

          {error && (
            <p className="text-base font-medium text-red-600">{error}</p>
          )}

          <div className="mt-2 flex gap-4">
            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
              className="min-h-[48px] flex-1 rounded-xl border border-gray-300 text-lg font-semibold text-gray-700 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={!canSubmit}
              className="flex min-h-[48px] flex-1 items-center justify-center gap-2 rounded-xl bg-amber-500 text-lg font-bold text-gray-900 hover:bg-amber-400 disabled:cursor-not-allowed disabled:bg-gray-300"
            >
              {isSubmitting && <Loader2 size={20} className="animate-spin" aria-hidden="true" />}
              {isSubmitting ? "新增中..." : "確認新增"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function ActiveToggle({ isActive, isToggling, onToggle }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={isActive}
      aria-label={isActive ? "點擊下架此餐點" : "點擊上架此餐點"}
      onClick={onToggle}
      disabled={isToggling}
      className={`flex min-h-[48px] w-24 items-center rounded-full p-1.5 transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
        isActive ? "justify-end bg-emerald-500" : "justify-start bg-gray-600"
      }`}
    >
      <span className="flex h-9 w-9 items-center justify-center rounded-full bg-white shadow">
        {isToggling && (
          <Loader2 size={18} className="animate-spin text-gray-500" aria-hidden="true" />
        )}
      </span>
    </button>
  );
}

function InventoryPanel({ items, isLoading, error, lastUpdatedAt, onRefresh, onAuthError }) {
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [isSubmittingAdd, setIsSubmittingAdd] = useState(false);
  const [addError, setAddError] = useState(null);
  const [togglingId, setTogglingId] = useState(null);
  const [toast, setToast] = useState(null); // { type: "success" | "error", message }

  const showToast = (type, message) => {
    setToast({ type, message });
    setTimeout(() => setToast(null), 3000);
  };

  const handleCreateItem = async (payload) => {
    setIsSubmittingAdd(true);
    setAddError(null);
    try {
      await axios.post("/api/menu", payload);
      setIsAddModalOpen(false);
      await onRefresh();
      showToast("success", "餐點新增成功！");
    } catch (err) {
      if (err.response?.status === 401) {
        onAuthError();
        return;
      }
      setAddError(err.response?.data?.message ?? "新增餐點失敗，請稍後再試");
    } finally {
      setIsSubmittingAdd(false);
    }
  };

  // 只送出 is_active，不需要 name/description/price：後端 PUT /api/menu/<id>
  // 採部分更新設計（只更新請求中出現的欄位），庫存 API 本身也不會回傳 description，
  // 若強行帶上舊值反而可能用空字串覆蓋掉餐點原有的描述。
  const handleToggleActive = async (item) => {
    setTogglingId(item.id);
    try {
      await axios.put(`/api/menu/${item.id}`, { is_active: !item.is_active });
      await onRefresh();
      showToast("success", `已${item.is_active ? "下架" : "上架"}「${item.name}」`);
    } catch (err) {
      if (err.response?.status === 401) {
        onAuthError();
        return;
      }
      showToast("error", err.response?.data?.message ?? "更新上架狀態失敗，請稍後再試");
    } finally {
      setTogglingId(null);
    }
  };

  return (
    <>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <p className="text-lg text-gray-300">
          品項總數：
          <span className="text-2xl font-bold text-amber-400">{items.length}</span>{" "}
          項
        </p>

        <div className="flex items-center gap-4">
          {lastUpdatedAt && (
            <span className="text-sm text-gray-400">
              最後更新：{lastUpdatedAt.toLocaleTimeString("zh-TW")}
            </span>
          )}
          <button
            type="button"
            onClick={onRefresh}
            className="flex min-h-[48px] min-w-[48px] items-center gap-2 rounded-xl border border-gray-600 px-4 text-lg font-semibold text-white hover:bg-gray-800"
          >
            <RefreshCw size={22} aria-hidden="true" />
            重新整理
          </button>
          <button
            type="button"
            onClick={() => {
              setAddError(null);
              setIsAddModalOpen(true);
            }}
            className="flex min-h-[48px] items-center gap-2 rounded-xl bg-amber-500 px-6 text-lg font-bold text-gray-900 shadow hover:bg-amber-400"
          >
            <Plus size={22} aria-hidden="true" />
            新增餐點
          </button>
        </div>
      </div>

      {isLoading && (
        <p className="py-16 text-center text-2xl text-gray-300">
          庫存載入中...
        </p>
      )}

      {!isLoading && error && (
        <p className="py-16 text-center text-2xl text-red-400">{error}</p>
      )}

      {!isLoading && !error && items.length === 0 && (
        <p className="py-16 text-center text-2xl text-gray-300">
          目前尚未建立任何餐點
        </p>
      )}

      {!isLoading && !error && items.length > 0 && (
        <div className="overflow-hidden rounded-2xl bg-gray-800 shadow-lg">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] text-left">
              <thead>
                <tr className="border-b border-gray-700 bg-gray-800/80 text-base font-semibold text-gray-300">
                  <th className="px-6 py-4">餐點名稱</th>
                  <th className="px-6 py-4">單價</th>
                  <th className="px-6 py-4">目前庫存</th>
                  <th className="px-6 py-4">上架狀態</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-700">
                {items.map((item) => (
                  <tr
                    key={item.id}
                    className="text-lg text-white odd:bg-gray-800 even:bg-gray-800/60 hover:bg-gray-700/60"
                  >
                    <td className="px-6 py-4 font-semibold">{item.name}</td>
                    <td className="px-6 py-4 text-gray-300">NT$ {item.price}</td>
                    <td className="px-6 py-4">
                      <span
                        className={`font-bold ${item.stock <= 5 ? "text-red-400" : "text-white"}`}
                      >
                        {item.stock}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-3">
                        <ActiveToggle
                          isActive={item.is_active}
                          isToggling={togglingId === item.id}
                          onToggle={() => handleToggleActive(item)}
                        />
                        <span
                          className={`text-base font-semibold ${
                            item.is_active ? "text-emerald-400" : "text-gray-400"
                          }`}
                        >
                          {togglingId === item.id
                            ? "更新中..."
                            : item.is_active
                              ? "上架中"
                              : "已下架"}
                        </span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {isAddModalOpen && (
        <AddMenuItemModal
          isSubmitting={isSubmittingAdd}
          error={addError}
          onConfirm={handleCreateItem}
          onClose={() => setIsAddModalOpen(false)}
        />
      )}

      {toast && (
        <div
          className={`fixed bottom-6 right-6 z-50 flex items-center gap-3 rounded-xl px-6 py-4 text-lg font-bold text-white shadow-2xl ${
            toast.type === "success" ? "bg-emerald-600" : "bg-red-600"
          }`}
        >
          {toast.type === "success" ? (
            <CircleCheck size={24} aria-hidden="true" />
          ) : (
            <AlertTriangle size={24} aria-hidden="true" />
          )}
          {toast.message}
        </div>
      )}
    </>
  );
}

function CouponPanel({ onAuthError }) {
  const [coupons, setCoupons] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [code, setCode] = useState("");
  const [discountType, setDiscountType] = useState("FIXED");
  const [discountValue, setDiscountValue] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState(null);

  const fetchCoupons = useCallback(async () => {
    try {
      const res = await axios.get("/api/coupons");
      setCoupons(res.data.coupons ?? []);
      setError(null);
    } catch (err) {
      if (err.response?.status === 401) {
        onAuthError();
        return;
      }
      setError(err.response?.data?.message ?? "無法取得優惠券資料，請稍後再試");
    } finally {
      setIsLoading(false);
    }
  }, [onAuthError]);

  useEffect(() => {
    fetchCoupons();
  }, [fetchCoupons]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setFormError(null);

    if (!code.trim()) {
      setFormError("請輸入優惠碼");
      return;
    }
    if (!discountValue || Number(discountValue) <= 0) {
      setFormError("折扣數值必須為正整數");
      return;
    }

    setIsSubmitting(true);
    try {
      await axios.post("/api/coupons", {
        code: code.trim(),
        discount_type: discountType,
        discount_value: Number(discountValue),
      });
      setCode("");
      setDiscountValue("");
      await fetchCoupons();
    } catch (err) {
      if (err.response?.status === 401) {
        onAuthError();
        return;
      }
      setFormError(err.response?.data?.message ?? "建立優惠券失敗，請稍後再試");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <>
      <form
        onSubmit={handleSubmit}
        className="mb-8 rounded-2xl bg-gray-800 p-6 shadow-lg"
      >
        <h2 className="mb-5 text-xl font-bold text-white">新增優惠券</h2>

        <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
          <div>
            <label className="mb-2 block text-sm font-semibold text-gray-300">
              優惠碼
            </label>
            <input
              type="text"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="例：OPEN888"
              className="min-h-[48px] w-full rounded-xl border border-gray-600 bg-gray-900 px-4 text-lg text-white placeholder:text-gray-500 focus:border-amber-400 focus:outline-none focus:ring-1 focus:ring-amber-400"
            />
          </div>

          <div>
            <label className="mb-2 block text-sm font-semibold text-gray-300">
              折扣類型
            </label>
            <select
              value={discountType}
              onChange={(e) => setDiscountType(e.target.value)}
              className="min-h-[48px] w-full rounded-xl border border-gray-600 bg-gray-900 px-4 text-lg text-white focus:border-amber-400 focus:outline-none focus:ring-1 focus:ring-amber-400"
            >
              <option value="FIXED">固定金額折抵</option>
              <option value="PERCENTAGE">百分比折扣</option>
            </select>
          </div>

          <div>
            <label className="mb-2 block text-sm font-semibold text-gray-300">
              折扣數值{discountType === "PERCENTAGE" ? "（%）" : "（NT$）"}
            </label>
            <input
              type="number"
              min="1"
              value={discountValue}
              onChange={(e) => setDiscountValue(e.target.value)}
              placeholder={discountType === "PERCENTAGE" ? "1-100" : "例：50"}
              className="min-h-[48px] w-full rounded-xl border border-gray-600 bg-gray-900 px-4 text-lg text-white placeholder:text-gray-500 focus:border-amber-400 focus:outline-none focus:ring-1 focus:ring-amber-400"
            />
          </div>
        </div>

        {formError && (
          <p className="mt-4 text-base font-medium text-red-400">{formError}</p>
        )}

        <button
          type="submit"
          disabled={isSubmitting}
          className="mt-5 flex min-h-[48px] items-center gap-2 rounded-xl bg-amber-500 px-6 text-lg font-bold text-gray-900 shadow hover:bg-amber-400 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Plus size={22} aria-hidden="true" />
          {isSubmitting ? "建立中..." : "新增優惠券"}
        </button>
      </form>

      {isLoading && (
        <p className="py-16 text-center text-2xl text-gray-300">
          優惠券載入中...
        </p>
      )}

      {!isLoading && error && (
        <p className="py-16 text-center text-2xl text-red-400">{error}</p>
      )}

      {!isLoading && !error && coupons.length === 0 && (
        <p className="py-16 text-center text-2xl text-gray-300">
          目前尚未建立任何優惠券
        </p>
      )}

      {!isLoading && !error && coupons.length > 0 && (
        <div className="overflow-hidden rounded-2xl bg-gray-800 shadow-lg">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-left">
              <thead>
                <tr className="border-b border-gray-700 bg-gray-800/80 text-base font-semibold text-gray-300">
                  <th className="px-6 py-4">優惠碼</th>
                  <th className="px-6 py-4">類型</th>
                  <th className="px-6 py-4">折扣數值</th>
                  <th className="px-6 py-4">狀態</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-700">
                {coupons.map((coupon) => (
                  <tr
                    key={coupon.id}
                    className="text-lg text-white odd:bg-gray-800 even:bg-gray-800/60 hover:bg-gray-700/60"
                  >
                    <td className="px-6 py-4 font-mono font-semibold tracking-wide">
                      {coupon.code}
                    </td>
                    <td className="px-6 py-4">
                      {DISCOUNT_TYPE_LABELS[coupon.discount_type] ?? coupon.discount_type}
                    </td>
                    <td className="px-6 py-4">
                      {coupon.discount_type === "PERCENTAGE"
                        ? `${coupon.discount_value}%`
                        : `NT$ ${coupon.discount_value}`}
                    </td>
                    <td className="px-6 py-4">
                      <span
                        className={`inline-flex items-center rounded-full px-3 py-1.5 text-sm font-semibold ${
                          coupon.is_active
                            ? "bg-emerald-100 text-emerald-800"
                            : "bg-gray-200 text-gray-600"
                        }`}
                      >
                        {coupon.is_active ? "啟用中" : "已停用"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}

function POSPanel({ inventoryItems, onAuthError, onOrderCreated }) {
  const [cart, setCart] = useState([]);
  const [paymentMethod, setPaymentMethod] = useState("CASH");
  const [pickupTime, setPickupTime] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const availableItems = inventoryItems.filter(
    (item) => item.is_active && item.stock > 0,
  );

  const addToCart = (item) => {
    setCart((prev) => {
      const existing = prev.find((cartItem) => cartItem.id === item.id);
      const currentQuantity = existing ? existing.quantity : 0;
      if (currentQuantity >= item.stock) {
        return prev;
      }
      if (existing) {
        return prev.map((cartItem) =>
          cartItem.id === item.id
            ? { ...cartItem, quantity: cartItem.quantity + 1 }
            : cartItem,
        );
      }
      return [...prev, { id: item.id, name: item.name, price: item.price, stock: item.stock, quantity: 1 }];
    });
  };

  const changeQuantity = (itemId, delta) => {
    setCart((prev) =>
      prev
        .map((cartItem) =>
          cartItem.id === itemId
            ? {
                ...cartItem,
                quantity: Math.min(cartItem.quantity + delta, cartItem.stock),
              }
            : cartItem,
        )
        .filter((cartItem) => cartItem.quantity > 0),
    );
  };

  const removeFromCart = (itemId) => {
    setCart((prev) => prev.filter((cartItem) => cartItem.id !== itemId));
  };

  const totalPrice = cart.reduce(
    (sum, item) => sum + item.price * item.quantity,
    0,
  );

  const handleSubmit = async () => {
    setError(null);

    if (cart.length === 0) {
      setError("請先點選餐點加入清單");
      return;
    }

    setIsSubmitting(true);
    try {
      await axios.post("/api/merchant/orders", {
        items: cart.map((item) => ({
          menu_item_id: item.id,
          quantity: item.quantity,
        })),
        payment_method: paymentMethod,
        pickup_time: pickupTime || undefined,
      });

      setCart([]);
      setPickupTime("");
      setPaymentMethod("CASH");
      onOrderCreated();
    } catch (err) {
      if (err.response?.status === 401) {
        onAuthError();
        return;
      }
      setError(err.response?.data?.message ?? "建立訂單失敗，請稍後再試");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_420px] lg:items-start">
      <div>
        <h2 className="mb-4 text-xl font-bold text-white">選擇餐點</h2>
        {availableItems.length === 0 ? (
          <p className="rounded-2xl bg-gray-800 py-16 text-center text-xl text-gray-300 shadow-lg">
            目前沒有可供銷售的餐點（庫存為 0 或已下架）
          </p>
        ) : (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-4">
            {availableItems.map((item) => {
              const inCartQuantity =
                cart.find((cartItem) => cartItem.id === item.id)?.quantity ?? 0;
              const isMaxed = inCartQuantity >= item.stock;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => addToCart(item)}
                  disabled={isMaxed}
                  className="flex min-h-[110px] flex-col justify-between rounded-2xl bg-gray-800 p-4 text-left shadow-lg transition-colors hover:bg-gray-700 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <span className="text-lg font-bold text-white">
                    {item.name}
                  </span>
                  <div className="flex items-center justify-between">
                    <span className="text-base font-semibold text-amber-400">
                      NT$ {item.price}
                    </span>
                    <span className="text-sm text-gray-400">
                      庫存 {item.stock}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>

      <div className="rounded-2xl bg-gray-800 p-6 shadow-lg lg:sticky lg:top-32">
        <h2 className="mb-4 flex items-center gap-2 text-xl font-bold text-white">
          <ShoppingCart size={24} aria-hidden="true" />
          結帳清單
        </h2>

        {cart.length === 0 ? (
          <p className="py-8 text-center text-lg text-gray-400">
            尚未點選任何餐點
          </p>
        ) : (
          <ul className="space-y-3">
            {cart.map((item) => (
              <li
                key={item.id}
                className="flex items-center justify-between gap-3 rounded-xl bg-gray-900 px-4 py-3"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-lg font-semibold text-white">
                    {item.name}
                  </p>
                  <p className="text-sm text-gray-400">
                    NT$ {item.price} x {item.quantity}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => changeQuantity(item.id, -1)}
                    className="flex h-10 w-10 items-center justify-center rounded-full border border-gray-600 text-white hover:bg-gray-700"
                  >
                    <Minus size={18} aria-hidden="true" />
                  </button>
                  <span className="w-6 text-center text-lg font-bold text-white">
                    {item.quantity}
                  </span>
                  <button
                    type="button"
                    onClick={() => changeQuantity(item.id, 1)}
                    disabled={item.quantity >= item.stock}
                    className="flex h-10 w-10 items-center justify-center rounded-full border border-gray-600 text-white hover:bg-gray-700 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    <Plus size={18} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    onClick={() => removeFromCart(item.id)}
                    className="flex h-10 w-10 items-center justify-center rounded-full text-red-400 hover:bg-red-950"
                  >
                    <Trash2 size={18} aria-hidden="true" />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}

        <div className="mt-5 flex items-center justify-between border-t border-gray-700 pt-4 text-xl font-bold text-white">
          <span>總金額</span>
          <span>NT$ {totalPrice}</span>
        </div>

        <div className="mt-5 border-t border-gray-700 pt-4">
          <h3 className="mb-3 text-sm font-semibold text-gray-300">付款方式</h3>
          <div className="flex gap-3">
            <label
              className={`flex flex-1 min-h-[48px] cursor-pointer items-center justify-center rounded-xl border px-4 text-base font-semibold transition-colors ${
                paymentMethod === "CASH"
                  ? "border-amber-400 bg-amber-500/10 text-amber-400"
                  : "border-gray-600 text-gray-300 hover:bg-gray-700"
              }`}
            >
              <input
                type="radio"
                name="pos_payment_method"
                value="CASH"
                checked={paymentMethod === "CASH"}
                onChange={() => setPaymentMethod("CASH")}
                className="sr-only"
              />
              現場現金
            </label>
            <label
              className={`flex flex-1 min-h-[48px] cursor-pointer items-center justify-center rounded-xl border px-4 text-base font-semibold transition-colors ${
                paymentMethod === "ONLINE"
                  ? "border-amber-400 bg-amber-500/10 text-amber-400"
                  : "border-gray-600 text-gray-300 hover:bg-gray-700"
              }`}
            >
              <input
                type="radio"
                name="pos_payment_method"
                value="ONLINE"
                checked={paymentMethod === "ONLINE"}
                onChange={() => setPaymentMethod("ONLINE")}
                className="sr-only"
              />
              線上刷卡
            </label>
          </div>
        </div>

        <div className="mt-5 border-t border-gray-700 pt-4">
          <h3 className="mb-3 text-sm font-semibold text-gray-300">
            預計取餐時間（電話訂餐可先填寫）
          </h3>
          <input
            type="datetime-local"
            value={pickupTime}
            onChange={(e) => setPickupTime(e.target.value)}
            className="min-h-[48px] w-full rounded-xl border border-gray-600 bg-gray-900 px-4 text-base text-white focus:border-amber-400 focus:outline-none focus:ring-1 focus:ring-amber-400"
          />
        </div>

        {error && (
          <p className="mt-4 text-base font-medium text-red-400">{error}</p>
        )}

        <button
          type="button"
          onClick={handleSubmit}
          disabled={isSubmitting || cart.length === 0}
          className="mt-6 flex min-h-[52px] w-full items-center justify-center gap-2 rounded-xl bg-amber-500 text-lg font-bold text-gray-900 shadow hover:bg-amber-400 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isSubmitting ? "送出中..." : "送出訂單"}
        </button>
      </div>
    </div>
  );
}

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
        <div className="mx-auto max-w-7xl">
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
      </header>

      <main className="mx-auto max-w-7xl px-6 py-8">
        {activeTab === "orders" && (
          <OrderBoardPanel onAuthError={handleAuthError} />
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
          <POSPanel
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
