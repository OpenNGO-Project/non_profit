frappe.treeview_settings["Chapter"] = {
	get_tree_nodes: "non_profit.non_profit.doctype.chapter.chapter.get_children",
	add_tree_node: "non_profit.non_profit.doctype.chapter.chapter.add_node",
	breadcrumb: "Non Profit",
	root_label: "All Chapters",
	get_tree_root: false,
	menu_items: [
		{
			label: __("New Chapter"),
			action: function () {
				frappe.new_doc("Chapter", true);
			},
			condition: 'frappe.boot.user.can_create.indexOf("Chapter") !== -1',
		},
	],
	onload: function (treeview) {
		treeview.make_tree();
	},
};
