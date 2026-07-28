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
  X,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Banknote,
  CreditCard,
} from "lucide-react";

const PAGE_SIZE = 8;
const AUTO_REFRESH_MS = 10000;

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
      label: "完成製作",
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

function MerchantDashboard() {
  const navigate = useNavigate();
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
    const token = localStorage.getItem("token");
    if (!token) {
      navigate("/auth", { state: { from: "/merchant" } });
      return;
    }

    try {
      const res = await axios.get("/api/orders");
      setOrders(res.data.orders ?? []);
      setError(null);
      setLastUpdatedAt(new Date());
    } catch (err) {
      if (err.response?.status === 401) {
        navigate("/auth", { state: { from: "/merchant" } });
        return;
      }
      setError(err.response?.data?.message ?? "無法取得訂單資料，請稍後再試");
    } finally {
      setIsLoading(false);
    }
  }, [navigate]);

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
    <div className="min-h-screen bg-gray-900">
      <header className="sticky top-0 z-30 border-b border-gray-800 bg-gray-900/95 px-6 py-5 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold text-white">商家接單大螢幕</h1>
            <p className="mt-1 text-lg text-gray-300">
              待處理總數：
              <span className="text-2xl font-bold text-amber-400">
                {activeOrders.length}
              </span>{" "}
              筆
            </p>
          </div>

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
      </header>

      <main className="mx-auto max-w-7xl px-6 py-8">
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
      </main>

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
    </div>
  );
}

export default MerchantDashboard;
