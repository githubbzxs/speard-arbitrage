export function formatCurrency(value: number): string {
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2
  }).format(value);
}

export function formatNumber(value: number, fractionDigits = 2): string {
  return new Intl.NumberFormat("zh-CN", {
    minimumFractionDigits: 0,
    maximumFractionDigits: fractionDigits
  }).format(value);
}

export function formatSigned(value: number, fractionDigits = 2): string {
  const abs = formatNumber(Math.abs(value), fractionDigits);
  if (value > 0) {
    return `+${abs}`;
  }
  if (value < 0) {
    return `-${abs}`;
  }
  return abs;
}

export function formatPrice(value: number): string {
  if (!Number.isFinite(value) || value <= 0) {
    return "--";
  }

  const abs = Math.abs(value);
  if (abs >= 1000) {
    return formatNumber(value, 2);
  }
  if (abs >= 1) {
    return formatNumber(value, 4);
  }
  return formatNumber(value, 6);
}

export function formatTimestamp(value: string): string {
  if (!value) {
    return "--";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString("zh-CN", { hour12: false });
}
