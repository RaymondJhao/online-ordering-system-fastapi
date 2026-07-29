import { useState } from "react";
import api from "../../lib/api";
import { extractErrorMessage } from "../../lib/errors";
import {
  RefreshCw,
  Plus,
  CircleCheck,
  Loader2,
  Pencil,
  AlertTriangle,
} from "lucide-react";

function MenuItemFormModal({
  title,
  submitLabel,
  submittingLabel,
  initialValues,
  isSubmitting,
  error,
  onConfirm,
  onClose,
}) {
  const [name, setName] = useState(initialValues?.name ?? "");
  const [description, setDescription] = useState(initialValues?.description ?? "");
  const [price, setPrice] = useState(
    initialValues?.price !== undefined ? String(initialValues.price) : "",
  );

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
        <h2 className="text-2xl font-bold text-gray-900">{title}</h2>

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
              {isSubmitting ? submittingLabel : submitLabel}
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
  const [editingItem, setEditingItem] = useState(null);
  const [isSubmittingEdit, setIsSubmittingEdit] = useState(false);
  const [editError, setEditError] = useState(null);
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
      await api.post("/api/menu", payload);
      setIsAddModalOpen(false);
      await onRefresh();
      showToast("success", "餐點新增成功！");
    } catch (err) {
      if (err.response?.status === 401) {
        onAuthError();
        return;
      }
      setAddError(extractErrorMessage(err, "新增餐點失敗，請稍後再試"));
    } finally {
      setIsSubmittingAdd(false);
    }
  };

  const handleUpdateItem = async (payload) => {
    setIsSubmittingEdit(true);
    setEditError(null);
    try {
      await api.put(`/api/menu/${editingItem.id}`, payload);
      setEditingItem(null);
      await onRefresh();
      showToast("success", `「${payload.name}」已更新`);
    } catch (err) {
      if (err.response?.status === 401) {
        onAuthError();
        return;
      }
      setEditError(extractErrorMessage(err, "更新餐點失敗，請稍後再試"));
    } finally {
      setIsSubmittingEdit(false);
    }
  };

  // 只送出 is_active，不需要 name/description/price：後端 PUT /api/menu/<id>
  // 採部分更新設計（只更新請求中出現的欄位），庫存 API 本身也不會回傳 description，
  // 若強行帶上舊值反而可能用空字串覆蓋掉餐點原有的描述。
  const handleToggleActive = async (item) => {
    setTogglingId(item.id);
    try {
      await api.put(`/api/menu/${item.id}`, { is_active: !item.is_active });
      await onRefresh();
      showToast("success", `已${item.is_active ? "下架" : "上架"}「${item.name}」`);
    } catch (err) {
      if (err.response?.status === 401) {
        onAuthError();
        return;
      }
      showToast("error", extractErrorMessage(err, "更新上架狀態失敗，請稍後再試"));
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
            <table className="w-full min-w-[680px] text-left">
              <thead>
                <tr className="border-b border-gray-700 bg-gray-800/80 text-base font-semibold text-gray-300">
                  <th className="px-6 py-4">餐點名稱</th>
                  <th className="px-6 py-4">單價</th>
                  <th className="px-6 py-4">目前庫存</th>
                  <th className="px-6 py-4">上架狀態</th>
                  <th className="px-6 py-4">操作</th>
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
                    <td className="px-6 py-4">
                      <button
                        type="button"
                        onClick={() => {
                          setEditError(null);
                          setEditingItem(item);
                        }}
                        className="flex min-h-[48px] items-center gap-2 rounded-xl border border-gray-600 px-4 text-base font-semibold text-white hover:bg-gray-700"
                      >
                        <Pencil size={18} aria-hidden="true" />
                        編輯
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {isAddModalOpen && (
        <MenuItemFormModal
          title="＋ 新增餐點"
          submitLabel="確認新增"
          submittingLabel="新增中..."
          isSubmitting={isSubmittingAdd}
          error={addError}
          onConfirm={handleCreateItem}
          onClose={() => setIsAddModalOpen(false)}
        />
      )}

      {editingItem && (
        <MenuItemFormModal
          title="編輯餐點"
          submitLabel="儲存變更"
          submittingLabel="更新中..."
          initialValues={editingItem}
          isSubmitting={isSubmittingEdit}
          error={editError}
          onConfirm={handleUpdateItem}
          onClose={() => setEditingItem(null)}
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

export default InventoryPanel;
