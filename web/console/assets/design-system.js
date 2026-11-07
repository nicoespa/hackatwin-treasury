/* @ds-bundle: {"format":4,"namespace":"ProfoundlyAIDesignSystem_bb6bcd","components":[{"name":"Icon","sourcePath":"components/brand/Icon.jsx"},{"name":"Logo","sourcePath":"components/brand/Logo.jsx"},{"name":"MarbleSurface","sourcePath":"components/brand/MarbleSurface.jsx"},{"name":"Badge","sourcePath":"components/display/Badge.jsx"},{"name":"Card","sourcePath":"components/display/Card.jsx"},{"name":"Tag","sourcePath":"components/display/Tag.jsx"},{"name":"Dialog","sourcePath":"components/feedback/Dialog.jsx"},{"name":"Toast","sourcePath":"components/feedback/Toast.jsx"},{"name":"Tooltip","sourcePath":"components/feedback/Tooltip.jsx"},{"name":"Button","sourcePath":"components/forms/Button.jsx"},{"name":"Checkbox","sourcePath":"components/forms/Checkbox.jsx"},{"name":"IconButton","sourcePath":"components/forms/IconButton.jsx"},{"name":"Input","sourcePath":"components/forms/Input.jsx"},{"name":"Radio","sourcePath":"components/forms/Radio.jsx"},{"name":"Select","sourcePath":"components/forms/Select.jsx"},{"name":"Switch","sourcePath":"components/forms/Switch.jsx"},{"name":"Tabs","sourcePath":"components/navigation/Tabs.jsx"}],"sourceHashes":{"components/brand/Icon.jsx":"ad51b0ac5d2d","components/brand/Logo.jsx":"e99ddf01a93e","components/brand/MarbleSurface.jsx":"a5e04a688eea","components/display/Badge.jsx":"b5501a5612b1","components/display/Card.jsx":"84c0befa34e3","components/display/Tag.jsx":"b4e25f8e0d81","components/feedback/Dialog.jsx":"5b4ac6c68920","components/feedback/Toast.jsx":"47d86d2c202b","components/feedback/Tooltip.jsx":"338bf2e0eb1d","components/forms/Button.jsx":"856d2462c6bf","components/forms/Checkbox.jsx":"173e8cf587d5","components/forms/IconButton.jsx":"f545ab211c0b","components/forms/Input.jsx":"f690618df8bc","components/forms/Radio.jsx":"2bf79c0c9b10","components/forms/Select.jsx":"cde6d87ced48","components/forms/Switch.jsx":"0585b8ec4d5b","components/navigation/Tabs.jsx":"78fb9cb62253","ui_kits/app/Chat.jsx":"cd64b3e834cb","ui_kits/app/Landing.jsx":"de1f17426c70","ui_kits/app/Sidebar.jsx":"4fba200c53e4","ui_kits/app/SignIn.jsx":"10ab33fe080d","ui_kits/app/Workspace.jsx":"df4460933edd"},"inlinedExternals":[],"unexposedExports":[]} */

(() => {

const __ds_ns = (window.ProfoundlyAIDesignSystem_bb6bcd = window.ProfoundlyAIDesignSystem_bb6bcd || {});

const __ds_scope = {};

(__ds_ns.__errors = __ds_ns.__errors || []);

// components/brand/Icon.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const CDN = 'https://unpkg.com/lucide-static@0.460.0/icons/';
function Icon({
  name,
  size = 20,
  color,
  className,
  style,
  label,
  ...rest
}) {
  return /*#__PURE__*/React.createElement("span", _extends({
    role: label ? 'img' : undefined,
    "aria-label": label,
    "aria-hidden": label ? undefined : true,
    className: ['pf-icon', className].filter(Boolean).join(' '),
    style: {
      width: size,
      height: size,
      '--src': `url(${CDN}${name}.svg)`,
      color,
      ...style
    }
  }, rest));
}
Object.assign(__ds_scope, { Icon });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/brand/Icon.jsx", error: String((e && e.message) || e) }); }

// components/brand/Logo.jsx
try { (() => {
function Logo({
  height = 40,
  className,
  style
}) {
  return /*#__PURE__*/React.createElement("span", {
    role: "img",
    "aria-label": "Profoundly AI",
    className: ['pf-logo', className].filter(Boolean).join(' '),
    style: {
      height,
      ...style
    }
  });
}
Object.assign(__ds_scope, { Logo });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/brand/Logo.jsx", error: String((e && e.message) || e) }); }

// components/brand/MarbleSurface.jsx
try { (() => {
const RADII = {
  organic: 'var(--radius-organic)',
  feature: 'var(--radius-feature)',
  panel: 'var(--radius-panel)',
  pill: 'var(--radius-pill)',
  none: 0
};
function MarbleSurface({
  shape = 'feature',
  texture = 'marble',
  width,
  height = 200,
  className,
  style,
  children
}) {
  const cls = texture === 'crosses' ? 'pf-crosses' : texture === 'ribbon' ? 'pf-marble-ribbon' : 'pf-marble';
  const bg = texture === 'crosses' ? {
    backgroundColor: 'var(--pf-petrol-900)'
  } : {};
  return /*#__PURE__*/React.createElement("div", {
    className: ['pf-marble-surface', cls, className].filter(Boolean).join(' '),
    style: {
      width,
      height,
      borderRadius: RADII[shape] ?? shape,
      ...bg,
      ...style
    }
  }, children);
}
Object.assign(__ds_scope, { MarbleSurface });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/brand/MarbleSurface.jsx", error: String((e && e.message) || e) }); }

// components/display/Badge.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const cx = (...a) => a.filter(Boolean).join(' ');
function Badge({
  tone = 'neutral',
  dot,
  children,
  className,
  ...rest
}) {
  return /*#__PURE__*/React.createElement("span", _extends({
    className: cx('pf-badge', 'pf-badge--' + tone, className)
  }, rest), dot && /*#__PURE__*/React.createElement("span", {
    className: "pf-badge__dot"
  }), children);
}
Object.assign(__ds_scope, { Badge });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/display/Badge.jsx", error: String((e && e.message) || e) }); }

// components/display/Card.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const cx = (...a) => a.filter(Boolean).join(' ');
function Card({
  variant = 'default',
  media,
  eyebrow,
  title,
  footer,
  interactive,
  children,
  className,
  style,
  bodyStyle,
  ...rest
}) {
  const mediaEl = media === 'marble' ? /*#__PURE__*/React.createElement("div", {
    className: "pf-card__media pf-marble"
  }) : media === 'crosses' ? /*#__PURE__*/React.createElement("div", {
    className: "pf-card__media pf-crosses",
    style: {
      background: 'var(--pf-petrol-900)'
    }
  }) : media;
  return /*#__PURE__*/React.createElement("div", _extends({
    className: cx('pf-card', variant !== 'default' && 'pf-card--' + variant, interactive && 'pf-card--interactive', className),
    style: style
  }, rest), mediaEl, (eyebrow || title || children) && /*#__PURE__*/React.createElement("div", {
    className: "pf-card__body",
    style: bodyStyle
  }, eyebrow && /*#__PURE__*/React.createElement("div", {
    className: "pf-card__eyebrow"
  }, eyebrow), title && /*#__PURE__*/React.createElement("h3", {
    className: "pf-card__title"
  }, title), children), footer && /*#__PURE__*/React.createElement("div", {
    className: "pf-card__footer"
  }, footer));
}
Object.assign(__ds_scope, { Card });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/display/Card.jsx", error: String((e && e.message) || e) }); }

// components/display/Tag.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const cx = (...a) => a.filter(Boolean).join(' ');
function Tag({
  selected,
  icon,
  onRemove,
  onClick,
  children,
  className,
  ...rest
}) {
  return /*#__PURE__*/React.createElement("span", _extends({
    role: onClick ? 'button' : undefined,
    tabIndex: onClick ? 0 : undefined,
    "aria-pressed": onClick ? !!selected : undefined,
    onClick: onClick,
    className: cx('pf-tag', selected && 'pf-tag--selected', className)
  }, rest), icon && /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: icon,
    size: 16
  }), children, onRemove && /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "pf-tag__x",
    "aria-label": "Quitar",
    onClick: e => {
      e.stopPropagation();
      onRemove(e);
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: "x",
    size: 14
  })));
}
Object.assign(__ds_scope, { Tag });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/display/Tag.jsx", error: String((e && e.message) || e) }); }

// components/feedback/Tooltip.jsx
try { (() => {
const cx = (...a) => a.filter(Boolean).join(' ');
function Tooltip({
  content,
  placement = 'top',
  open,
  children
}) {
  const [show, setShow] = React.useState(false);
  const vis = open ?? show;
  return /*#__PURE__*/React.createElement("span", {
    className: "pf-tooltip-wrap",
    onMouseEnter: () => setShow(true),
    onMouseLeave: () => setShow(false),
    onFocus: () => setShow(true),
    onBlur: () => setShow(false)
  }, children, vis && /*#__PURE__*/React.createElement("span", {
    role: "tooltip",
    className: cx('pf-tooltip', placement === 'bottom' && 'pf-tooltip--bottom')
  }, content));
}
Object.assign(__ds_scope, { Tooltip });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/feedback/Tooltip.jsx", error: String((e && e.message) || e) }); }

// components/forms/Button.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const cx = (...a) => a.filter(Boolean).join(' ');
function Button({
  variant = 'primary',
  size = 'md',
  block,
  iconLeft,
  iconRight,
  children,
  className,
  type = 'button',
  ...rest
}) {
  const is = size === 'sm' ? 16 : 18;
  return /*#__PURE__*/React.createElement("button", _extends({
    type: type,
    className: cx('pf-btn', 'pf-btn--' + variant, size !== 'md' && 'pf-btn--' + size, block && 'pf-btn--block', className)
  }, rest), iconLeft && /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: iconLeft,
    size: is
  }), children, iconRight && /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: iconRight,
    size: is
  }));
}
Object.assign(__ds_scope, { Button });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Button.jsx", error: String((e && e.message) || e) }); }

// components/forms/Checkbox.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const cx = (...a) => a.filter(Boolean).join(' ');
function Checkbox({
  label,
  description,
  disabled,
  className,
  style,
  ...rest
}) {
  return /*#__PURE__*/React.createElement("label", {
    className: cx('pf-check', '', disabled && 'pf-check--disabled', className),
    style: style
  }, /*#__PURE__*/React.createElement("input", _extends({
    type: "checkbox",
    disabled: disabled
  }, rest)), /*#__PURE__*/React.createElement("span", {
    className: "pf-check__box"
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: "check",
    size: 14
  })), (label || description) && /*#__PURE__*/React.createElement("span", null, label, description && /*#__PURE__*/React.createElement("span", {
    className: "pf-check__desc"
  }, description)));
}
Object.assign(__ds_scope, { Checkbox });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Checkbox.jsx", error: String((e && e.message) || e) }); }

// components/forms/IconButton.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const cx = (...a) => a.filter(Boolean).join(' ');
function IconButton({
  icon,
  label,
  variant = 'ghost',
  size = 'md',
  className,
  type = 'button',
  ...rest
}) {
  return /*#__PURE__*/React.createElement("button", _extends({
    type: type,
    "aria-label": label,
    title: label,
    className: cx('pf-btn', 'pf-iconbtn', 'pf-btn--' + variant, size !== 'md' && 'pf-btn--' + size, className)
  }, rest), /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: icon,
    size: size === 'sm' ? 16 : size === 'lg' ? 22 : 18
  }));
}
Object.assign(__ds_scope, { IconButton });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/IconButton.jsx", error: String((e && e.message) || e) }); }

// components/feedback/Dialog.jsx
try { (() => {
const cx = (...a) => a.filter(Boolean).join(' ');
function Dialog({
  open = true,
  onClose,
  title,
  description,
  footer,
  contained,
  width,
  children
}) {
  if (!open) return null;
  return /*#__PURE__*/React.createElement("div", {
    className: cx('pf-overlay', contained && 'pf-overlay--contained'),
    onClick: e => {
      if (e.target === e.currentTarget && onClose) onClose();
    }
  }, /*#__PURE__*/React.createElement("div", {
    role: "dialog",
    "aria-modal": "true",
    className: "pf-dialog",
    style: width ? {
      maxWidth: width
    } : undefined
  }, /*#__PURE__*/React.createElement("div", {
    className: "pf-dialog__head"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }, title && /*#__PURE__*/React.createElement("h2", {
    className: "pf-dialog__title"
  }, title), description && /*#__PURE__*/React.createElement("p", {
    className: "pf-dialog__desc"
  }, description)), onClose && /*#__PURE__*/React.createElement(__ds_scope.IconButton, {
    icon: "x",
    label: "Cerrar",
    size: "sm",
    onClick: onClose,
    style: {
      margin: '-4px -8px 0 0'
    }
  })), children && /*#__PURE__*/React.createElement("div", {
    className: "pf-dialog__body"
  }, children), footer && /*#__PURE__*/React.createElement("div", {
    className: "pf-dialog__foot"
  }, footer)));
}
Object.assign(__ds_scope, { Dialog });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/feedback/Dialog.jsx", error: String((e && e.message) || e) }); }

// components/feedback/Toast.jsx
try { (() => {
const cx = (...a) => a.filter(Boolean).join(' ');
const TONES = {
  success: ['check', 'var(--status-success-bg)', 'var(--status-success-fg)'],
  info: ['sparkles', 'var(--status-info-bg)', 'var(--status-info-fg)'],
  warning: ['alert-triangle', 'var(--status-warning-bg)', 'var(--status-warning-fg)'],
  danger: ['alert-circle', 'var(--status-danger-bg)', 'var(--status-danger-fg)']
};
function Toast({
  tone = 'success',
  title,
  description,
  action,
  onClose,
  inverse,
  className,
  style
}) {
  const [ic, bg, fg] = TONES[tone];
  return /*#__PURE__*/React.createElement("div", {
    role: "status",
    className: cx('pf-toast', inverse && 'pf-toast--inverse', className),
    style: style
  }, /*#__PURE__*/React.createElement("span", {
    className: "pf-toast__icon",
    style: {
      background: bg,
      color: fg
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: ic,
    size: 16
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      paddingTop: 4
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "pf-toast__title"
  }, title), description && /*#__PURE__*/React.createElement("div", {
    className: "pf-toast__desc"
  }, description), action && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 10
    }
  }, action)), onClose && /*#__PURE__*/React.createElement(__ds_scope.IconButton, {
    icon: "x",
    label: "Cerrar",
    size: "sm",
    onClick: onClose,
    style: inverse ? {
      color: '#fff'
    } : undefined
  }));
}
Object.assign(__ds_scope, { Toast });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/feedback/Toast.jsx", error: String((e && e.message) || e) }); }

// components/forms/Input.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const cx = (...a) => a.filter(Boolean).join(' ');
function Input({
  label,
  hint,
  error,
  iconLeft,
  trailing,
  multiline,
  rows = 3,
  size = 'md',
  disabled,
  id,
  className,
  style,
  ...rest
}) {
  const fid = id || React.useId();
  const Tag = multiline ? 'textarea' : 'input';
  return /*#__PURE__*/React.createElement("div", {
    className: cx('pf-field', className),
    style: style
  }, label && /*#__PURE__*/React.createElement("label", {
    className: "pf-field__label",
    htmlFor: fid
  }, label), /*#__PURE__*/React.createElement("div", {
    className: cx('pf-control', error && 'pf-control--error', disabled && 'pf-control--disabled', size === 'lg' && 'pf-control--lg'),
    style: multiline ? {
      alignItems: 'flex-start'
    } : undefined
  }, iconLeft && /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: iconLeft,
    size: 18
  }), /*#__PURE__*/React.createElement(Tag, _extends({
    id: fid,
    disabled: disabled,
    rows: multiline ? rows : undefined,
    "aria-invalid": !!error || undefined
  }, rest)), trailing), (error || hint) && /*#__PURE__*/React.createElement("div", {
    className: cx('pf-field__hint', error && 'pf-field__hint--error')
  }, error || hint));
}
Object.assign(__ds_scope, { Input });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Input.jsx", error: String((e && e.message) || e) }); }

// components/forms/Radio.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const cx = (...a) => a.filter(Boolean).join(' ');
function Radio({
  label,
  description,
  disabled,
  className,
  style,
  ...rest
}) {
  return /*#__PURE__*/React.createElement("label", {
    className: cx('pf-check', 'pf-check--radio', disabled && 'pf-check--disabled', className),
    style: style
  }, /*#__PURE__*/React.createElement("input", _extends({
    type: "radio",
    disabled: disabled
  }, rest)), /*#__PURE__*/React.createElement("span", {
    className: "pf-check__box"
  }), (label || description) && /*#__PURE__*/React.createElement("span", null, label, description && /*#__PURE__*/React.createElement("span", {
    className: "pf-check__desc"
  }, description)));
}
Object.assign(__ds_scope, { Radio });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Radio.jsx", error: String((e && e.message) || e) }); }

// components/forms/Select.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const cx = (...a) => a.filter(Boolean).join(' ');
function Select({
  label,
  hint,
  error,
  options = [],
  placeholder,
  disabled,
  id,
  className,
  style,
  ...rest
}) {
  const fid = id || React.useId();
  return /*#__PURE__*/React.createElement("div", {
    className: cx('pf-field', className),
    style: style
  }, label && /*#__PURE__*/React.createElement("label", {
    className: "pf-field__label",
    htmlFor: fid
  }, label), /*#__PURE__*/React.createElement("div", {
    className: cx('pf-control', error && 'pf-control--error', disabled && 'pf-control--disabled')
  }, /*#__PURE__*/React.createElement("select", _extends({
    id: fid,
    disabled: disabled,
    defaultValue: rest.value === undefined && placeholder ? '' : undefined
  }, rest), placeholder && /*#__PURE__*/React.createElement("option", {
    value: "",
    disabled: true
  }, placeholder), options.map(o => typeof o === 'string' ? /*#__PURE__*/React.createElement("option", {
    key: o,
    value: o
  }, o) : /*#__PURE__*/React.createElement("option", {
    key: o.value,
    value: o.value
  }, o.label))), /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: "chevron-down",
    size: 18,
    style: {
      pointerEvents: 'none'
    }
  })), (error || hint) && /*#__PURE__*/React.createElement("div", {
    className: cx('pf-field__hint', error && 'pf-field__hint--error')
  }, error || hint));
}
Object.assign(__ds_scope, { Select });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Select.jsx", error: String((e && e.message) || e) }); }

// components/forms/Switch.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const cx = (...a) => a.filter(Boolean).join(' ');
function Switch({
  label,
  description,
  disabled,
  className,
  style,
  ...rest
}) {
  return /*#__PURE__*/React.createElement("label", {
    className: cx('pf-check', '', disabled && 'pf-check--disabled', className),
    style: style
  }, /*#__PURE__*/React.createElement("input", _extends({
    type: "checkbox",
    disabled: disabled,
    role: "switch"
  }, rest)), /*#__PURE__*/React.createElement("span", {
    className: "pf-switch__track"
  }), (label || description) && /*#__PURE__*/React.createElement("span", null, label, description && /*#__PURE__*/React.createElement("span", {
    className: "pf-check__desc"
  }, description)));
}
Object.assign(__ds_scope, { Switch });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Switch.jsx", error: String((e && e.message) || e) }); }

// components/navigation/Tabs.jsx
try { (() => {
const cx = (...a) => a.filter(Boolean).join(' ');
function Tabs({
  items = [],
  value,
  defaultValue,
  onChange,
  variant = 'underline',
  className,
  style
}) {
  const [inner, setInner] = React.useState(defaultValue ?? items[0]?.value);
  const cur = value ?? inner;
  return /*#__PURE__*/React.createElement("div", {
    role: "tablist",
    className: cx('pf-tabs', variant === 'pill' && 'pf-tabs--pill', className),
    style: style
  }, items.map(it => /*#__PURE__*/React.createElement("button", {
    key: it.value,
    role: "tab",
    type: "button",
    "aria-selected": cur === it.value,
    className: "pf-tab",
    onClick: () => {
      setInner(it.value);
      onChange && onChange(it.value);
    }
  }, it.label, it.count != null && /*#__PURE__*/React.createElement("span", {
    className: "pf-tab__count"
  }, it.count))));
}
Object.assign(__ds_scope, { Tabs });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/navigation/Tabs.jsx", error: String((e && e.message) || e) }); }

// ui_kits/app/Chat.jsx
try { (() => {
(() => {
  const {
    Icon,
    IconButton,
    Tag,
    Badge,
    Tooltip
  } = window.ProfoundlyAIDesignSystem_bb6bcd;
  function Message({
    m
  }) {
    if (m.role === 'user') return /*#__PURE__*/React.createElement("div", {
      style: {
        alignSelf: 'flex-end',
        maxWidth: '72%',
        background: 'var(--surface-inverse)',
        color: '#fff',
        padding: '12px 16px',
        borderRadius: '20px 20px 6px 20px',
        font: 'var(--type-body)'
      }
    }, m.text);
    return /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        gap: 14,
        maxWidth: '86%'
      }
    }, /*#__PURE__*/React.createElement("span", {
      className: "pf-marble",
      style: {
        width: 32,
        height: 32,
        borderRadius: '50%',
        flex: 'none'
      }
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
        paddingTop: 4
      }
    }, m.pending ? /*#__PURE__*/React.createElement("span", {
      style: {
        color: 'var(--text-muted)',
        font: 'var(--type-body)'
      }
    }, "Leyendo tus documentos\u2026") : /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
      style: {
        font: 'var(--type-body)',
        color: 'var(--text-body)',
        whiteSpace: 'pre-line'
      }
    }, m.text), m.sources && /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        gap: 6,
        flexWrap: 'wrap'
      }
    }, m.sources.map(s => /*#__PURE__*/React.createElement(Badge, {
      key: s,
      tone: "neutral"
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "file-text",
      size: 12
    }), s))), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        gap: 2,
        marginLeft: -8
      }
    }, /*#__PURE__*/React.createElement(Tooltip, {
      content: "Copiar"
    }, /*#__PURE__*/React.createElement(IconButton, {
      icon: "copy",
      label: "Copiar",
      size: "sm"
    })), /*#__PURE__*/React.createElement(Tooltip, {
      content: "\xDAtil"
    }, /*#__PURE__*/React.createElement(IconButton, {
      icon: "thumbs-up",
      label: "\xDAtil",
      size: "sm"
    })), /*#__PURE__*/React.createElement(Tooltip, {
      content: "Regenerar"
    }, /*#__PURE__*/React.createElement(IconButton, {
      icon: "refresh-cw",
      label: "Regenerar",
      size: "sm"
    }))))));
  }
  function Composer({
    onSend
  }) {
    const [v, setV] = React.useState('');
    const send = () => {
      if (!v.trim()) return;
      onSend(v.trim());
      setV('');
    };
    return /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexDirection: 'column',
        gap: 12
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        gap: 8,
        flexWrap: 'wrap'
      }
    }, ['Resumir en 5 puntos', 'Comparar Q2 y Q3', 'Riesgos principales'].map(s => /*#__PURE__*/React.createElement(Tag, {
      key: s,
      icon: "sparkles",
      onClick: () => onSend(s)
    }, s))), /*#__PURE__*/React.createElement("div", {
      className: "pf-control",
      style: {
        borderRadius: 'var(--radius-xl)',
        padding: '8px 8px 8px 18px',
        boxShadow: 'var(--shadow-sm)'
      }
    }, /*#__PURE__*/React.createElement("input", {
      value: v,
      onChange: e => setV(e.target.value),
      onKeyDown: e => e.key === 'Enter' && send(),
      placeholder: "Pregunt\xE1 lo que necesites sobre este espacio"
    }), /*#__PURE__*/React.createElement(IconButton, {
      icon: "paperclip",
      label: "Adjuntar"
    }), /*#__PURE__*/React.createElement(IconButton, {
      icon: "arrow-up",
      label: "Enviar",
      variant: "primary",
      onClick: send,
      disabled: !v.trim()
    })));
  }
  function Chat({
    messages,
    onSend
  }) {
    const ref = React.useRef(null);
    React.useEffect(() => {
      if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
    }, [messages]);
    return /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        minHeight: 0
      }
    }, /*#__PURE__*/React.createElement("div", {
      ref: ref,
      style: {
        flex: 1,
        overflow: 'auto',
        padding: '28px 0',
        display: 'flex',
        flexDirection: 'column',
        gap: 24
      }
    }, messages.map((m, i) => /*#__PURE__*/React.createElement(Message, {
      key: i,
      m: m
    }))), /*#__PURE__*/React.createElement(Composer, {
      onSend: onSend
    }));
  }
  Object.assign(window, {
    Chat
  });
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/app/Chat.jsx", error: String((e && e.message) || e) }); }

// ui_kits/app/Landing.jsx
try { (() => {
(() => {
  const {
    Logo,
    Button,
    Card,
    Icon,
    MarbleSurface,
    Badge
  } = window.ProfoundlyAIDesignSystem_bb6bcd;
  function Landing({
    go
  }) {
    const feats = [['upload', 'Subí lo que ya tenés', 'PDFs, notas, planillas. Los leemos por vos y los dejamos listos para consultar.'], ['message-circle', 'Preguntá como hablás', 'Sin comandos ni jerga. Escribí la duda y recibí una respuesta clara, con fuentes.'], ['check-circle', 'Decidí con contexto', 'Resúmenes, comparaciones y próximos pasos, en un solo lugar.']];
    return /*#__PURE__*/React.createElement("div", {
      className: "pf-grain",
      style: {
        minHeight: '100vh'
      }
    }, /*#__PURE__*/React.createElement("header", {
      style: {
        maxWidth: 1200,
        margin: '0 auto',
        padding: '22px 32px',
        display: 'flex',
        alignItems: 'center',
        gap: 32
      }
    }, /*#__PURE__*/React.createElement(Logo, {
      height: 28
    }), /*#__PURE__*/React.createElement("nav", {
      style: {
        display: 'flex',
        gap: 4,
        marginLeft: 16
      }
    }, ['Producto', 'Casos', 'Precios'].map(l => /*#__PURE__*/React.createElement(Button, {
      key: l,
      variant: "ghost",
      size: "sm"
    }, l))), /*#__PURE__*/React.createElement("div", {
      style: {
        marginLeft: 'auto',
        display: 'flex',
        gap: 8
      }
    }, /*#__PURE__*/React.createElement(Button, {
      variant: "ghost",
      onClick: () => go('signin')
    }, "Ingresar"), /*#__PURE__*/React.createElement(Button, {
      onClick: () => go('signin')
    }, "Probar gratis"))), /*#__PURE__*/React.createElement("section", {
      className: "pf-marble-ribbon",
      style: {
        maxWidth: 1200,
        margin: '8px auto 0',
        minHeight: 560,
        borderRadius: 'var(--radius-feature)',
        display: 'flex',
        alignItems: 'center',
        padding: '0 72px',
        backgroundSize: 'cover'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        maxWidth: 560,
        display: 'flex',
        flexDirection: 'column',
        gap: 24
      }
    }, /*#__PURE__*/React.createElement(Badge, {
      tone: "accent"
    }, "Nuevo \xB7 Espacios compartidos"), /*#__PURE__*/React.createElement("h1", {
      style: {
        font: 'var(--type-display)',
        letterSpacing: 'var(--tracking-display)'
      }
    }, "Pens\xE1 m\xE1s hondo. Decid\xED m\xE1s claro."), /*#__PURE__*/React.createElement("p", {
      style: {
        font: 'var(--type-body-lg)',
        color: 'var(--text-muted)',
        maxWidth: 460
      }
    }, "Profoundly AI ordena tus documentos y responde tus preguntas con fuentes. Simple, directo y a tu ritmo."), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        gap: 12
      }
    }, /*#__PURE__*/React.createElement(Button, {
      size: "lg",
      iconRight: "arrow-right",
      onClick: () => go('signin')
    }, "Empezar gratis"), /*#__PURE__*/React.createElement(Button, {
      size: "lg",
      variant: "outline"
    }, "Ver c\xF3mo funciona")))), /*#__PURE__*/React.createElement("section", {
      style: {
        maxWidth: 1200,
        margin: '0 auto',
        padding: '96px 32px',
        display: 'flex',
        flexDirection: 'column',
        gap: 40
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
        maxWidth: 560
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        font: 'var(--type-label)',
        letterSpacing: 'var(--tracking-label)',
        textTransform: 'uppercase',
        color: 'var(--text-accent)'
      }
    }, "C\xF3mo funciona"), /*#__PURE__*/React.createElement("h2", null, "Tres pasos, sin vueltas.")), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'grid',
        gridTemplateColumns: 'repeat(3, minmax(0,1fr))',
        gap: 20
      }
    }, feats.map(([ic, t, d], i) => /*#__PURE__*/React.createElement(Card, {
      key: t,
      title: t,
      bodyStyle: {
        gap: 12,
        padding: 28
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        order: -1,
        width: 44,
        height: 44,
        borderRadius: 14,
        display: 'grid',
        placeItems: 'center',
        background: 'var(--surface-mint-soft)',
        color: 'var(--text-strong)',
        marginBottom: 8
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: ic
    })), /*#__PURE__*/React.createElement("p", {
      style: {
        color: 'var(--text-muted)'
      }
    }, d))))), /*#__PURE__*/React.createElement("section", {
      style: {
        maxWidth: 1200,
        margin: '0 auto 96px',
        padding: '0 32px'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        background: 'var(--surface-soft)',
        borderRadius: 'var(--radius-feature)',
        padding: 56,
        display: 'flex',
        alignItems: 'center',
        gap: 48
      }
    }, /*#__PURE__*/React.createElement(MarbleSurface, {
      shape: "organic",
      width: 220,
      height: 220,
      style: {
        flex: 'none'
      }
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexDirection: 'column',
        gap: 16,
        flex: 1
      }
    }, /*#__PURE__*/React.createElement("h2", null, "Tu equipo, en la misma p\xE1gina."), /*#__PURE__*/React.createElement("p", {
      style: {
        font: 'var(--type-body-lg)',
        color: 'var(--text-muted)',
        maxWidth: 520
      }
    }, "Compart\xED espacios, dej\xE1 notas sobre cada respuesta y retom\xE1 donde lo dej\xF3 otra persona."), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(Button, {
      variant: "secondary",
      iconRight: "arrow-right",
      onClick: () => go('signin')
    }, "Crear un espacio"))))), /*#__PURE__*/React.createElement("footer", {
      style: {
        borderTop: '1px solid var(--border-subtle)'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        maxWidth: 1200,
        margin: '0 auto',
        padding: '28px 32px',
        display: 'flex',
        alignItems: 'center',
        gap: 24,
        font: 'var(--type-body-sm)',
        color: 'var(--text-muted)'
      }
    }, /*#__PURE__*/React.createElement(Logo, {
      height: 20
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        marginLeft: 'auto'
      }
    }, "Privacidad"), /*#__PURE__*/React.createElement("span", null, "T\xE9rminos"), /*#__PURE__*/React.createElement("span", null, "\xA9 2026 Profoundly AI"))));
  }
  window.Landing = Landing;
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/app/Landing.jsx", error: String((e && e.message) || e) }); }

// ui_kits/app/Sidebar.jsx
try { (() => {
(() => {
  const {
    Logo,
    Button,
    Icon,
    IconButton,
    Tooltip
  } = window.ProfoundlyAIDesignSystem_bb6bcd;
  function Sidebar({
    spaces,
    active,
    onSelect,
    onNew,
    onLogout
  }) {
    return /*#__PURE__*/React.createElement("aside", {
      style: {
        width: 260,
        flex: 'none',
        display: 'flex',
        flexDirection: 'column',
        gap: 20,
        padding: '22px 16px',
        borderRight: '1px solid var(--border-subtle)',
        background: 'var(--surface-page)'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        padding: '0 8px'
      }
    }, /*#__PURE__*/React.createElement(Logo, {
      height: 22
    })), /*#__PURE__*/React.createElement(Button, {
      block: true,
      iconLeft: "plus",
      onClick: onNew
    }, "Nuevo espacio"), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexDirection: 'column',
        gap: 2
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        font: 'var(--type-label)',
        letterSpacing: 'var(--tracking-label)',
        textTransform: 'uppercase',
        color: 'var(--text-subtle)',
        padding: '0 10px 8px'
      }
    }, "Espacios"), spaces.map(s => {
      const on = s.id === active;
      return /*#__PURE__*/React.createElement("button", {
        key: s.id,
        onClick: () => onSelect(s.id),
        style: {
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          height: 40,
          padding: '0 10px',
          border: 0,
          borderRadius: 'var(--radius-sm)',
          cursor: 'pointer',
          textAlign: 'left',
          background: on ? 'var(--surface-mint-soft)' : 'transparent',
          color: on ? 'var(--text-strong)' : 'var(--text-body)',
          font: 'var(--weight-' + (on ? 'semibold' : 'medium') + ') 14px/1 var(--font-sans)'
        }
      }, /*#__PURE__*/React.createElement("span", {
        className: on ? 'pf-marble' : '',
        style: {
          width: 18,
          height: 18,
          borderRadius: 6,
          flex: 'none',
          background: on ? undefined : 'var(--pf-grey-200)'
        }
      }), /*#__PURE__*/React.createElement("span", {
        style: {
          flex: 1,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap'
        }
      }, s.name), /*#__PURE__*/React.createElement("span", {
        style: {
          font: 'var(--type-mono)',
          fontSize: 11,
          color: 'var(--text-subtle)'
        }
      }, s.docs));
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: 'auto',
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '12px 8px 0',
        borderTop: '1px solid var(--border-subtle)'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 32,
        height: 32,
        borderRadius: '50%',
        background: 'var(--surface-mint)',
        color: 'var(--text-strong)',
        display: 'grid',
        placeItems: 'center',
        font: 'var(--weight-semibold) 13px var(--font-sans)'
      }
    }, "AR"), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        lineHeight: 1.25
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        font: 'var(--weight-semibold) 14px var(--font-sans)',
        color: 'var(--text-strong)'
      }
    }, "Ana R\xEDos"), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12,
        color: 'var(--text-muted)'
      }
    }, "Plan Equipo")), /*#__PURE__*/React.createElement(Tooltip, {
      content: "Salir"
    }, /*#__PURE__*/React.createElement(IconButton, {
      icon: "log-out",
      label: "Salir",
      size: "sm",
      onClick: onLogout
    }))));
  }
  window.Sidebar = Sidebar;
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/app/Sidebar.jsx", error: String((e && e.message) || e) }); }

// ui_kits/app/SignIn.jsx
try { (() => {
(() => {
  const {
    Logo,
    Button,
    Input,
    Checkbox,
    MarbleSurface
  } = window.ProfoundlyAIDesignSystem_bb6bcd;
  function SignIn({
    go
  }) {
    const [email, setEmail] = React.useState('ana@estudio.com');
    const [err, setErr] = React.useState('');
    const submit = e => {
      e.preventDefault();
      if (!email.includes('@')) return setErr('Revisá el email: le falta la @.');
      go('workspace');
    };
    return /*#__PURE__*/React.createElement("div", {
      style: {
        minHeight: '100vh',
        display: 'grid',
        gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)',
        padding: 20,
        gap: 20,
        background: 'var(--surface-page)'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexDirection: 'column',
        padding: '20px 40px'
      }
    }, /*#__PURE__*/React.createElement("button", {
      onClick: () => go('landing'),
      style: {
        background: 'none',
        border: 0,
        padding: 0,
        cursor: 'pointer',
        alignSelf: 'flex-start'
      }
    }, /*#__PURE__*/React.createElement(Logo, {
      height: 26
    })), /*#__PURE__*/React.createElement("form", {
      onSubmit: submit,
      style: {
        margin: 'auto',
        width: '100%',
        maxWidth: 380,
        display: 'flex',
        flexDirection: 'column',
        gap: 20
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexDirection: 'column',
        gap: 8
      }
    }, /*#__PURE__*/React.createElement("h2", null, "Hola de nuevo"), /*#__PURE__*/React.createElement("p", {
      style: {
        color: 'var(--text-muted)'
      }
    }, "Ingres\xE1 para seguir con tus espacios.")), /*#__PURE__*/React.createElement(Input, {
      label: "Email",
      size: "lg",
      value: email,
      onChange: e => {
        setEmail(e.target.value);
        setErr('');
      },
      error: err
    }), /*#__PURE__*/React.createElement(Input, {
      label: "Contrase\xF1a",
      size: "lg",
      type: "password",
      defaultValue: "secreto123"
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center'
      }
    }, /*#__PURE__*/React.createElement(Checkbox, {
      label: "Recordarme",
      defaultChecked: true
    }), /*#__PURE__*/React.createElement("a", {
      href: "#",
      style: {
        font: 'var(--type-body-sm)'
      }
    }, "Olvid\xE9 mi contrase\xF1a")), /*#__PURE__*/React.createElement(Button, {
      type: "submit",
      size: "lg",
      block: true
    }, "Ingresar"), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        color: 'var(--text-subtle)',
        font: 'var(--type-body-sm)'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        flex: 1,
        height: 1,
        background: 'var(--border-subtle)'
      }
    }), "o", /*#__PURE__*/React.createElement("span", {
      style: {
        flex: 1,
        height: 1,
        background: 'var(--border-subtle)'
      }
    })), /*#__PURE__*/React.createElement(Button, {
      variant: "outline",
      size: "lg",
      block: true,
      iconLeft: "mail",
      onClick: () => go('workspace')
    }, "Recibir enlace por email"), /*#__PURE__*/React.createElement("p", {
      style: {
        font: 'var(--type-body-sm)',
        color: 'var(--text-muted)',
        textAlign: 'center'
      }
    }, "\xBFNo ten\xE9s cuenta? ", /*#__PURE__*/React.createElement("a", {
      href: "#"
    }, "Creala gratis")))), /*#__PURE__*/React.createElement(MarbleSurface, {
      shape: "panel",
      height: "auto",
      style: {
        minHeight: 'calc(100vh - 40px)',
        display: 'flex',
        alignItems: 'flex-end',
        padding: 32
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        background: 'var(--surface-card)',
        borderRadius: 'var(--radius-xl)',
        padding: 24,
        maxWidth: 380,
        boxShadow: 'var(--shadow-md)'
      }
    }, /*#__PURE__*/React.createElement("p", {
      style: {
        font: 'var(--type-body-lg)',
        color: 'var(--text-strong)'
      }
    }, "\u201CPasamos de leer 40 informes a hacer 3 buenas preguntas.\u201D"), /*#__PURE__*/React.createElement("p", {
      style: {
        font: 'var(--type-body-sm)',
        color: 'var(--text-muted)',
        marginTop: 10
      }
    }, "Luc\xEDa M. \xB7 Directora de estrategia"))));
  }
  window.SignIn = SignIn;
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/app/SignIn.jsx", error: String((e && e.message) || e) }); }

// ui_kits/app/Workspace.jsx
try { (() => {
(() => {
  const {
    Tabs,
    Button,
    Card,
    Badge,
    Icon,
    IconButton,
    Dialog,
    Toast,
    Input,
    Switch
  } = window.ProfoundlyAIDesignSystem_bb6bcd;
  const SPACES = [{
    id: 'mk',
    name: 'Investigación de mercado',
    docs: 12
  }, {
    id: 'q3',
    name: 'Cierre Q3',
    docs: 7
  }, {
    id: 'pr',
    name: 'Propuesta Fundación',
    docs: 4
  }];
  const DOCS = [['Informe Q3.pdf', '2,4 MB · hoy'], ['Encuesta clientes.xlsx', '880 KB · ayer'], ['Notas de entrevistas.docx', '140 KB · lun'], ['Benchmark 2026.pdf', '5,1 MB · 28 oct']];
  const FIRST = [{
    role: 'user',
    text: '¿Qué cambió en la demanda entre Q2 y Q3?'
  }, {
    role: 'ai',
    text: 'La demanda creció un 14 % en Q3. Tres motivos explican la mayor parte:\n\n1. Más pedidos de clientes medianos (+22 %).\n2. Menos cancelaciones tras el cambio de precios.\n3. Un pico estacional en septiembre.',
    sources: ['Informe Q3.pdf · p. 4', 'Encuesta clientes.xlsx']
  }];
  function Workspace({
    go
  }) {
    const [space, setSpace] = React.useState('mk');
    const [tab, setTab] = React.useState('chat');
    const [msgs, setMsgs] = React.useState(FIRST);
    const [toast, setToast] = React.useState(null);
    const [dlg, setDlg] = React.useState(false);
    const flash = t => {
      setToast(t);
      clearTimeout(window.__pfT);
      window.__pfT = setTimeout(() => setToast(null), 3500);
    };
    const send = text => {
      setMsgs(m => [...m, {
        role: 'user',
        text
      }, {
        role: 'ai',
        pending: true
      }]);
      setTimeout(() => setMsgs(m => [...m.slice(0, -1), {
        role: 'ai',
        text: 'Listo. En corto: el crecimiento viene de clientes medianos y se sostiene si mantenemos los precios actuales. Te marco las fuentes abajo.',
        sources: ['Informe Q3.pdf · p. 7']
      }]), 1100);
    };
    const cur = SPACES.find(s => s.id === space);
    return /*#__PURE__*/React.createElement("div", {
      style: {
        height: '100vh',
        display: 'flex',
        background: 'var(--surface-page)'
      }
    }, /*#__PURE__*/React.createElement(Sidebar, {
      spaces: SPACES,
      active: space,
      onSelect: setSpace,
      onNew: () => flash({
        title: 'Espacio creado',
        description: 'Subí documentos para empezar.'
      }),
      onLogout: () => go('landing')
    }), /*#__PURE__*/React.createElement("main", {
      style: {
        flex: 1,
        minWidth: 0,
        display: 'flex',
        flexDirection: 'column',
        padding: '20px 40px 28px'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 12
      }
    }, /*#__PURE__*/React.createElement("h3", {
      style: {
        fontSize: 22,
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        minWidth: 0
      }
    }, cur.name), /*#__PURE__*/React.createElement(Badge, {
      tone: "accent",
      style: {
        flex: 'none',
        alignSelf: 'center'
      }
    }, cur.docs, " documentos"), /*#__PURE__*/React.createElement("div", {
      style: {
        marginLeft: 'auto',
        display: 'flex',
        gap: 6,
        flex: 'none'
      }
    }, /*#__PURE__*/React.createElement(Button, {
      variant: "outline",
      size: "sm",
      iconLeft: "user-plus"
    }, "Compartir"), /*#__PURE__*/React.createElement(IconButton, {
      icon: "trash-2",
      label: "Eliminar espacio",
      size: "sm",
      onClick: () => setDlg(true)
    }))), /*#__PURE__*/React.createElement(Tabs, {
      value: tab,
      onChange: setTab,
      style: {
        marginTop: 14
      },
      items: [{
        value: 'chat',
        label: 'Chat'
      }, {
        value: 'docs',
        label: 'Documentos',
        count: cur.docs
      }, {
        value: 'set',
        label: 'Ajustes'
      }]
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        minHeight: 0,
        display: 'flex',
        flexDirection: 'column',
        maxWidth: 820,
        width: '100%',
        margin: '0 auto'
      }
    }, tab === 'chat' && /*#__PURE__*/React.createElement(Chat, {
      messages: msgs,
      onSend: send
    }), tab === 'docs' && /*#__PURE__*/React.createElement("div", {
      style: {
        paddingTop: 28,
        display: 'flex',
        flexDirection: 'column',
        gap: 16
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        gap: 12
      }
    }, /*#__PURE__*/React.createElement(Input, {
      iconLeft: "search",
      placeholder: "Buscar en documentos",
      style: {
        flex: 1
      }
    }), /*#__PURE__*/React.createElement(Button, {
      variant: "secondary",
      iconLeft: "upload",
      onClick: () => flash({
        title: 'Documento subido',
        description: 'Ya podés hacerle preguntas.'
      })
    }, "Subir")), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'grid',
        gridTemplateColumns: 'repeat(2,minmax(0,1fr))',
        gap: 14
      }
    }, DOCS.map(([n, meta]) => /*#__PURE__*/React.createElement(Card, {
      key: n,
      interactive: true,
      bodyStyle: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 14,
        padding: 18
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 40,
        height: 40,
        borderRadius: 12,
        background: 'var(--surface-soft)',
        display: 'grid',
        placeItems: 'center',
        color: 'var(--text-strong)'
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "file-text"
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        minWidth: 0
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        font: 'var(--weight-semibold) 15px var(--font-sans)',
        color: 'var(--text-strong)'
      }
    }, n), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 13,
        color: 'var(--text-muted)'
      }
    }, meta)), /*#__PURE__*/React.createElement(Badge, {
      tone: "success",
      dot: true
    }, "Listo"))))), tab === 'set' && /*#__PURE__*/React.createElement("div", {
      style: {
        paddingTop: 28
      }
    }, /*#__PURE__*/React.createElement(Card, {
      title: "Respuestas",
      bodyStyle: {
        gap: 18
      }
    }, /*#__PURE__*/React.createElement(Switch, {
      label: "Citar fuentes siempre",
      description: "Cada respuesta incluye de d\xF3nde sale.",
      defaultChecked: true
    }), /*#__PURE__*/React.createElement(Switch, {
      label: "Respuestas breves",
      description: "M\xE1ximo 5 oraciones, salvo que pidas m\xE1s."
    }), /*#__PURE__*/React.createElement(Switch, {
      label: "Compartir historial con el equipo",
      defaultChecked: true
    }))))), toast && /*#__PURE__*/React.createElement("div", {
      style: {
        position: 'fixed',
        right: 24,
        bottom: 24,
        zIndex: 200
      }
    }, /*#__PURE__*/React.createElement(Toast, {
      title: toast.title,
      description: toast.description,
      onClose: () => setToast(null)
    })), /*#__PURE__*/React.createElement(Dialog, {
      open: dlg,
      onClose: () => setDlg(false),
      title: "\xBFEliminar este espacio?",
      description: 'Se borran sus ' + cur.docs + ' documentos y el historial. No se puede deshacer.',
      footer: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Button, {
        variant: "ghost",
        onClick: () => setDlg(false)
      }, "Cancelar"), /*#__PURE__*/React.createElement(Button, {
        variant: "danger",
        onClick: () => {
          setDlg(false);
          flash({
            title: 'Espacio eliminado'
          });
        }
      }, "Eliminar"))
    }));
  }
  window.Workspace = Workspace;
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/app/Workspace.jsx", error: String((e && e.message) || e) }); }

__ds_ns.Icon = __ds_scope.Icon;

__ds_ns.Logo = __ds_scope.Logo;

__ds_ns.MarbleSurface = __ds_scope.MarbleSurface;

__ds_ns.Badge = __ds_scope.Badge;

__ds_ns.Card = __ds_scope.Card;

__ds_ns.Tag = __ds_scope.Tag;

__ds_ns.Dialog = __ds_scope.Dialog;

__ds_ns.Toast = __ds_scope.Toast;

__ds_ns.Tooltip = __ds_scope.Tooltip;

__ds_ns.Button = __ds_scope.Button;

__ds_ns.Checkbox = __ds_scope.Checkbox;

__ds_ns.IconButton = __ds_scope.IconButton;

__ds_ns.Input = __ds_scope.Input;

__ds_ns.Radio = __ds_scope.Radio;

__ds_ns.Select = __ds_scope.Select;

__ds_ns.Switch = __ds_scope.Switch;

__ds_ns.Tabs = __ds_scope.Tabs;

})();
