import { useState } from "react";
import axios from "axios";
import { ShoppingCart, Plus, Minus, Trash2 } from "lucide-react";

function ManualOrderForm({ inventoryItems, onAuthError, onOrderCreated }) {
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

export default ManualOrderForm;
