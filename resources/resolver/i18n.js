function interpolate(message, values) {
  if (!values) {
    return message;
  }
  return String(message).replace(/%\(([^)]+)\)s/g, (match, key) =>
    Object.prototype.hasOwnProperty.call(values, key) ? String(values[key]) : match,
  );
}

export function gettext(message, values = null) {
  const translated =
    typeof globalThis.gettext === "function" ? globalThis.gettext(message) : message;
  return interpolate(translated, values);
}

export function ngettext(singular, plural, count, values = null) {
  const translated =
    typeof globalThis.ngettext === "function"
      ? globalThis.ngettext(singular, plural, count)
      : count === 1
      ? singular
      : plural;
  return interpolate(translated, { ...values, count });
}
