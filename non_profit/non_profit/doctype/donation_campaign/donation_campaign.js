frappe.ui.form.on("Donation Campaign", {
	refresh(frm) {
		window.renderCampaignDonationChart?.(frm);
		if (!frm.is_new()) {
			frm.page.add_action_item(__("Refresh Totals"), () => {
				frm.call("refresh_totals").then(() => frm.reload_doc());
			});
		}
	},
});

(function () {
	"use strict";

	const CHART_COLORS = ["#14527a", "#6f7f2f", "#b1842e", "#7b5a8e", "#3f6f68", "#a45d45", "#5f6f89"];
	const CHART_SECTION_SELECTOR = ".non-profit-campaign-chart-section";

	injectCampaignChartStyles();
	setupCampaignChartClicks();

	function injectCampaignChartStyles() {
		if (document.getElementById("non-profit-campaign-chart-styles")) return;
		$(`<style id="non-profit-campaign-chart-styles">
			.non-profit-campaign-chart-section {
				box-sizing: border-box;
				width: 100%;
				max-width: 100%;
				margin-top: 18px;
				margin-bottom: 0;
				border: 0;
				box-shadow: none;
			}
			.non-profit-campaign-chart-section .section-body {
				box-sizing: border-box;
				width: 100%;
				max-width: 100%;
			}
			.non-profit-campaign-donation-chart {
				box-sizing: border-box;
				width: 100%;
				max-width: 100%;
				padding: 18px;
				border: 0;
				border-radius: 8px;
				background: transparent;
				box-shadow: none;
				overflow-x: clip;
			}
			.non-profit-campaign-chart-head {
				display: flex;
				align-items: flex-start;
				justify-content: space-between;
				gap: 14px;
				margin-bottom: 18px;
			}
			.non-profit-campaign-chart-title {
				display: inline-flex;
				align-items: baseline;
				gap: 10px;
				color: var(--heading-color);
				font-size: 22px;
				line-height: 1.2;
				font-weight: 700;
			}
			.non-profit-campaign-chart-year-picker { position: relative; display: inline-block; }
			.non-profit-campaign-chart-year {
				display: inline-flex;
				align-items: center;
				gap: 4px;
				width: auto;
				min-width: 78px;
				height: auto;
				padding: 0 18px 0 0;
				border: 0;
				background: transparent;
				color: var(--heading-color);
				font: inherit;
				font-weight: 700;
				list-style: none;
				cursor: pointer;
			}
			.non-profit-campaign-chart-year::-webkit-details-marker { display: none; }
			.non-profit-campaign-chart-year::after {
				content: "";
				position: absolute;
				right: 0;
				top: 50%;
				width: 7px;
				height: 7px;
				border-right: 2px solid currentColor;
				border-bottom: 2px solid currentColor;
				transform: translateY(-65%) rotate(45deg);
			}
			.non-profit-campaign-chart-year-picker[open] .non-profit-campaign-chart-year::after {
				transform: translateY(-30%) rotate(225deg);
			}
			.non-profit-campaign-chart-year-menu {
				position: absolute;
				top: calc(100% + 6px);
				left: 0;
				z-index: 5;
				min-width: 112px;
				padding: 6px;
				border: 1px solid var(--border-color);
				border-radius: 8px;
				background: var(--card-bg);
				box-shadow: 0 12px 28px rgba(25, 22, 51, 0.16);
			}
			.non-profit-campaign-chart-year-option {
				display: block;
				width: 100%;
				padding: 7px 10px;
				border: 0;
				border-radius: 6px;
				background: transparent;
				color: var(--text-color);
				font-size: 13px;
				font-weight: 600;
				text-align: left;
				cursor: pointer;
			}
			.non-profit-campaign-chart-year-option:hover,
			.non-profit-campaign-chart-year-option:focus-visible {
				background: var(--control-bg);
				outline: none;
			}
			.non-profit-campaign-chart-year-option.is-selected {
				background: var(--highlight-color);
				color: var(--primary);
			}
			.non-profit-campaign-chart-total {
				color: var(--heading-color);
				font-size: 22px;
				line-height: 1.1;
				font-weight: 700;
				text-align: right;
				overflow-wrap: anywhere;
			}
			.non-profit-campaign-chart-total-label {
				margin-bottom: 4px;
				color: var(--text-muted);
				font-size: 12px;
				line-height: 1.2;
				font-weight: 600;
				text-transform: uppercase;
			}
			.non-profit-campaign-chart-plot {
				--non-profit-campaign-chart-height: 132px;
				position: relative;
				display: grid;
				grid-template-columns: 54px minmax(0, 1fr);
				gap: 10px;
				align-items: start;
				min-width: 0;
				max-width: 100%;
			}
			.non-profit-campaign-chart-axis { position: relative; height: var(--non-profit-campaign-chart-height); overflow: visible; }
			.non-profit-campaign-chart-axis span {
				position: absolute;
				right: 0;
				transform: translateY(50%);
				color: var(--text-muted);
				font-size: 11px;
				white-space: nowrap;
			}
			.non-profit-campaign-chart-grid {
				position: absolute;
				inset: 0 0 0 64px;
				height: var(--non-profit-campaign-chart-height);
				pointer-events: none;
			}
			.non-profit-campaign-chart-grid span {
				position: absolute;
				left: 0;
				right: 0;
				border-top: 1px solid var(--border-color);
			}
			.non-profit-campaign-chart-bars {
				display: grid;
				grid-template-columns: repeat(12, minmax(0, 1fr));
				gap: 8px;
				min-width: 0;
				height: calc(var(--non-profit-campaign-chart-height) + 24px);
				min-height: 0;
				align-items: end;
			}
			.non-profit-campaign-chart-month {
				display: grid;
				grid-template-rows: var(--non-profit-campaign-chart-height) auto;
				gap: 8px;
				min-width: 0;
				height: auto;
			}
			.non-profit-campaign-chart-bar-track {
				display: flex;
				align-items: flex-end;
				height: var(--non-profit-campaign-chart-height);
				min-height: 0;
				border-radius: 6px;
				background: var(--subtle-fg);
				overflow: visible;
			}
			.non-profit-campaign-chart-bar {
				display: flex;
				flex-direction: column-reverse;
				width: 100%;
				min-height: 0;
				border-radius: 6px 6px 0 0;
				overflow: visible;
			}
			.non-profit-campaign-chart-segment {
				position: relative;
				z-index: 1;
				display: block;
				width: 100%;
				min-height: 2px;
				border: 0;
				padding: 0;
				cursor: pointer;
				transition: filter 0.15s ease, box-shadow 0.15s ease;
			}
			.non-profit-campaign-chart-segment:hover,
			.non-profit-campaign-chart-segment:focus-visible {
				z-index: 20;
				filter: brightness(1.08);
				box-shadow: inset 0 0 0 2px rgba(255, 255, 255, 0.55);
				outline: none;
			}
			.non-profit-campaign-chart-segment::after {
				content: attr(data-tooltip);
				position: absolute;
				left: 50%;
				bottom: calc(100% + 8px);
				z-index: 30;
				width: max-content;
				max-width: 220px;
				padding: 6px 8px;
				border-radius: 6px;
				background: var(--gray-900);
				color: #fff;
				font-size: 11px;
				line-height: 1.35;
				white-space: normal;
				box-shadow: 0 8px 18px rgba(25, 22, 51, 0.22);
				opacity: 0;
				pointer-events: none;
				transform: translateX(-50%) translateY(4px);
				transition: opacity 0.12s ease, transform 0.12s ease;
			}
			.non-profit-campaign-chart-segment:hover::after,
			.non-profit-campaign-chart-segment:focus-visible::after {
				opacity: 1;
				transform: translateX(-50%) translateY(0);
			}
			.non-profit-campaign-chart-label {
				color: var(--text-muted);
				font-size: 11px;
				text-align: center;
				white-space: nowrap;
				overflow: hidden;
			}
			@media (max-width: 720px) {
				.non-profit-campaign-chart-head { flex-direction: column; }
				.non-profit-campaign-chart-total { text-align: left; }
				.non-profit-campaign-chart-plot { grid-template-columns: 46px minmax(0, 1fr); gap: 8px; }
				.non-profit-campaign-chart-grid { left: 54px; }
				.non-profit-campaign-chart-bars { gap: 5px; }
				.non-profit-campaign-chart-label { font-size: 10px; }
			}
		</style>`).appendTo(document.head);
	}

	function setupCampaignChartClicks() {
		$(document)
			.off("click.nonProfitCampaignChart", ".non-profit-campaign-chart-segment")
			.on("click.nonProfitCampaignChart", ".non-profit-campaign-chart-segment", function (event) {
				event.preventDefault();
				event.stopPropagation();
				const doctype = this.getAttribute("data-route-form");
				const docname = this.getAttribute("data-docname");
				if (doctype && docname) frappe.set_route("Form", doctype, docname);
			});
		$(document)
			.off("click.nonProfitCampaignChart", "[data-non-profit-campaign-chart-year-option]")
			.on("click.nonProfitCampaignChart", "[data-non-profit-campaign-chart-year-option]", function (event) {
				event.preventDefault();
				if (cur_frm?.doctype !== "Donation Campaign") return;
				const selectedYear =
					Number(this.getAttribute("data-non-profit-campaign-chart-year-option")) ||
					cur_frm.non_profit_campaign_chart_year;
				$(this).closest(".non-profit-campaign-chart-year-picker").removeAttr("open");
				if (selectedYear === cur_frm.non_profit_campaign_chart_year) return;
				cur_frm.non_profit_campaign_chart_year = selectedYear;
				renderCampaignDonationChart(cur_frm, {
					loading: false,
					scrollTop: window.scrollY,
				});
			});
	}

	window.renderCampaignDonationChart = function (frm, options = {}) {
		frm.non_profit_campaign_chart_request = (frm.non_profit_campaign_chart_request || 0) + 1;
		renderCampaignDonationChartForRequest(frm, frm.non_profit_campaign_chart_request, 0, options);
	};

	function renderCampaignDonationChartForRequest(frm, requestId, attempt = 0, options = {}) {
		if (!frm || frm.non_profit_campaign_chart_request !== requestId) return;
		if (options.loading !== false) {
			removeCampaignDonationChart(frm);
		}
		if (frm.is_new() || !frm.doc?.name) return;
		if (!frm.dashboard?.links_area?.wrapper) {
			if (attempt < 20) {
				window.setTimeout(
					() => renderCampaignDonationChartForRequest(frm, requestId, attempt + 1, options),
					100
				);
			}
			return;
		}
		frappe
			.call({
				method:
					"non_profit.non_profit.doctype.donation_campaign.donation_campaign.get_campaign_donation_chart",
				args: {
					campaign: frm.doc.name,
					year: frm.non_profit_campaign_chart_year,
				},
			})
			.then((response) => {
				if (frm.non_profit_campaign_chart_request !== requestId) return;
				if (frm.is_new() || frm.doc?.name !== response.message?.campaign) return;
				removeCampaignDonationChart(frm);
				frm.non_profit_campaign_chart_year = response.message.year || frm.non_profit_campaign_chart_year;
				const section = $(campaignDonationChartHtml(response.message || {}));
				frm.dashboard.links_area.wrapper.before(section);
				frm.dashboard.show();
				restoreScroll(options.scrollTop);
			});
	}

	function restoreScroll(scrollTop) {
		if (typeof scrollTop !== "number") return;
		window.requestAnimationFrame(() => window.scrollTo(window.scrollX, scrollTop));
	}

	function removeCampaignDonationChart(frm) {
		const wrapper = frm?.dashboard?.parent || frm?.layout?.wrapper;
		if (wrapper?.find) {
			wrapper.find(CHART_SECTION_SELECTOR).remove();
		} else {
			$(CHART_SECTION_SELECTOR).remove();
		}
	}

	function campaignDonationChartHtml(data) {
		const currency = data.currency || frappe.boot?.sysdefaults?.currency || "EUR";
		const months = normalizeMonthlyDonations(data.donations_by_month || []);
		const maxValue = Math.max(...months.map((row) => row.total), 0);
		const axisTicks = donationAxisTicks(maxValue);
		const axisMax = axisTicks[0]?.value || maxValue || 0;
		const bars = months.map((row) => monthHtml(row, axisMax, currency)).join("");
		const yearSelect = chartYearSelect(data.year, data.year_options || []);
		return `<div class="form-dashboard-section card-section non-profit-campaign-chart-section">
			<div class="section-body">
				<div class="non-profit-campaign-donation-chart">
					<div class="non-profit-campaign-chart-head">
						<div class="non-profit-campaign-chart-title">
							<span>${escapeHtml(__("Donations"))}</span>${yearSelect}
						</div>
						<div class="non-profit-campaign-chart-total">
							<div class="non-profit-campaign-chart-total-label">${escapeHtml(__("Total"))}</div>
							${escapeHtml(format_currency(data.total || 0, currency))}
						</div>
					</div>
					<div class="non-profit-campaign-chart-plot">
						<div class="non-profit-campaign-chart-axis" aria-hidden="true">
							${axisTicks.map((tick) => `<span style="bottom:${tick.position}%">${escapeHtml(shortMoney(tick.value))}</span>`).join("")}
						</div>
						<div class="non-profit-campaign-chart-grid" aria-hidden="true">
							${axisTicks.map((tick) => `<span style="bottom:${tick.position}%"></span>`).join("")}
						</div>
						<div class="non-profit-campaign-chart-bars" aria-label="${escapeHtml(__("Donations per Month"))}">${bars}</div>
					</div>
				</div>
			</div>
		</div>`;
	}

	function chartYearSelect(selectedYear, yearOptions) {
		const year = Number(selectedYear) || new Date().getFullYear();
		const options = (yearOptions?.length ? yearOptions : Array.from({ length: 5 }, (_, index) => year - index)).map(
			(option) => Number(option)
		);
		return `<details class="non-profit-campaign-chart-year-picker">
			<summary class="non-profit-campaign-chart-year" aria-label="${escapeHtml(__("Year"))}">${escapeHtml(String(year))}</summary>
			<div class="non-profit-campaign-chart-year-menu" role="listbox">${options
				.map(
					(option) =>
						`<button class="non-profit-campaign-chart-year-option${
							option === year ? " is-selected" : ""
						}" type="button" role="option" aria-selected="${
							option === year ? "true" : "false"
						}" data-non-profit-campaign-chart-year-option="${option}">${option}</button>`
				)
				.join("")}</div>
		</details>`;
	}

	function monthHtml(row, axisMax, currency) {
		const label = monthLabel(row.month);
		const amount = format_currency(row.total || 0, currency);
		const height = axisMax > 0 ? Math.max(4, Math.round((row.total / axisMax) * 100)) : 0;
		const segments = row.segments
			.map((segment, index) => {
				const segmentHeight = row.total ? Math.max(3, (segment.total / row.total) * 100) : 0;
				const title = `${segment.label}: ${format_currency(segment.total || 0, currency)}`;
				return `<a class="non-profit-campaign-chart-segment" href="/desk/donation/${encodeURIComponent(
					segment.donation
				)}" data-route-form="Donation" data-docname="${escapeHtml(segment.donation)}" style="height:${segmentHeight}%; background:${chartColor(
					index
				)}" title="${escapeHtml(title)}" data-tooltip="${escapeHtml(title)}" aria-label="${escapeHtml(title)}"></a>`;
			})
			.join("");
		return `<div class="non-profit-campaign-chart-month" title="${escapeHtml(`${label}: ${amount}`)}">
			<div class="non-profit-campaign-chart-bar-track">
				<div class="non-profit-campaign-chart-bar" style="height:${height}%">${segments}</div>
			</div>
			<div class="non-profit-campaign-chart-label">${escapeHtml(label)}</div>
		</div>`;
	}

	function normalizeMonthlyDonations(monthlyDonations) {
		return Array.from({ length: 12 }, (_, index) => {
			const month = index + 1;
			const row = (monthlyDonations || []).find((item) => Number(item.month) === month) || {};
			return {
				month,
				total: Number(row.total) || 0,
				segments: (row.segments || [])
					.map((segment) => ({
						donation: segment.donation || "",
						label: segment.label || segment.donation || __("Donation"),
						total: Number(segment.total) || 0,
					}))
					.filter((segment) => segment.donation && segment.total > 0),
			};
		});
	}

	function donationAxisTicks(maxValue) {
		if (!(maxValue > 0)) return [{ value: 0, position: 0 }];
		const upper = niceAxisUpper(maxValue);
		return [
			{ value: upper, position: 100 },
			{ value: upper / 2, position: 50 },
			{ value: 0, position: 0 },
		];
	}

	function niceAxisUpper(maxValue) {
		const magnitude = 10 ** Math.floor(Math.log10(maxValue));
		const normalized = maxValue / magnitude;
		const niceNormalized = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
		return niceNormalized * magnitude;
	}

	function shortMoney(value) {
		const amount = Number(value) || 0;
		if (amount === 0) return "0";
		if (amount >= 1000000) return `${compactNumber(amount / 1000000)}M`;
		if (amount >= 1000) return `${compactNumber(amount / 1000)}k`;
		return compactNumber(amount);
	}

	function compactNumber(value) {
		return new Intl.NumberFormat(frappe.boot.lang || undefined, { maximumFractionDigits: 1 }).format(Number(value) || 0);
	}

	function chartColor(index) {
		return CHART_COLORS[index % CHART_COLORS.length];
	}

	function monthLabel(month) {
		try {
			return new Intl.DateTimeFormat(frappe.boot.lang || undefined, { month: "short" })
				.format(new Date(2000, month - 1, 1))
				.replace(".", "");
		} catch {
			return String(month);
		}
	}

	function escapeHtml(value) {
		return String(value || "")
			.replace(/&/g, "&amp;")
			.replace(/</g, "&lt;")
			.replace(/>/g, "&gt;")
			.replace(/"/g, "&quot;")
			.replace(/'/g, "&#039;");
	}
})();
