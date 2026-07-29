import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { Plus } from "lucide-react";

const DISCOUNT_TYPE_LABELS = {
  PERCENTAGE: "百分比折扣",
  FIXED: "固定金額折抵",
};

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

export default CouponPanel;
