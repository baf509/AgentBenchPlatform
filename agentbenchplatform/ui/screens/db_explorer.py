"""Database explorer screen — browse MongoDB databases, collections, and indexes."""

from __future__ import annotations

import json
import logging

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Footer, RichLog, Static, Tree
from textual.widgets._tree import TreeNode

from agentbenchplatform.ui.screens.base import BaseScreen

logger = logging.getLogger(__name__)


class DatabaseExplorerScreen(BaseScreen):
    """Explore connected MongoDB databases, collections, indexes, and search indexes."""

    BINDINGS = [
        ("escape", "pop_screen", "Back"),
        ("q", "quit", "Quit"),
        ("f5", "refresh", "Refresh"),
    ]

    def compose(self) -> ComposeResult:
        yield Static("Database Explorer", id="db-title")
        with Horizontal(id="db-container"):
            yield Tree("Server", id="db-tree")
            yield RichLog(id="db-detail", wrap=True, markup=False)
        yield Footer()

    async def on_mount(self) -> None:
        tree = self.query_one("#db-tree", Tree)
        tree.root.expand()
        await self._refresh()

    async def _refresh(self) -> None:
        if not self.has_context():
            detail = self.query_one("#db-detail", RichLog)
            detail.clear()
            detail.write("Not connected to MongoDB.")
            return

        tree = self.query_one("#db-tree", Tree)
        tree.root.remove_children()

        # Use RPC-based db_explorer if available, fall back to direct mongo access
        if hasattr(self.ctx, "db_explorer"):
            await self._refresh_via_rpc(tree)
        elif hasattr(self.ctx, "mongo"):
            await self._refresh_direct(tree)
        else:
            detail = self.query_one("#db-detail", RichLog)
            detail.clear()
            detail.write("Database Explorer requires database access.")
            return

        tree.root.expand()

    async def _refresh_via_rpc(self, tree: Tree) -> None:
        """Populate tree using RPC calls (works in client mode)."""
        try:
            db_names = await self.ctx.db_explorer.list_databases()
        except Exception:
            logger.debug("Could not list databases via RPC", exc_info=True)
            detail = self.query_one("#db-detail", RichLog)
            detail.clear()
            detail.write("Error listing databases. Check MongoDB connection.")
            return

        for db_name in sorted(db_names):
            db_node = tree.root.add(f"{db_name}", data={"type": "database", "name": db_name})

            try:
                coll_names = await self.ctx.db_explorer.list_collections(db_name)
            except Exception:
                logger.debug("Could not list collections for %s", db_name, exc_info=True)
                db_node.add_leaf("(error listing collections)")
                continue

            for coll_name in sorted(coll_names):
                try:
                    info = await self.ctx.db_explorer.collection_info(db_name, coll_name)
                    doc_count = info.get("doc_count", "?")
                except Exception:
                    doc_count = "?"

                coll_node = db_node.add(
                    f"{coll_name} ({doc_count} docs)",
                    data={
                        "type": "collection",
                        "db": db_name,
                        "name": coll_name,
                        "doc_count": doc_count,
                    },
                )

                # Standard indexes
                idx_node = coll_node.add("Indexes", data={"type": "indexes_group"})
                try:
                    indexes = await self.ctx.db_explorer.collection_indexes(db_name, coll_name)
                    for idx_name, idx_info in sorted(indexes.items()):
                        unique = " (unique)" if idx_info.get("unique") else ""
                        idx_node.add_leaf(
                            f"{idx_name}{unique}",
                            data={
                                "type": "index",
                                "db": db_name,
                                "collection": coll_name,
                                "name": idx_name,
                                "info": idx_info,
                            },
                        )
                except Exception:
                    idx_node.add_leaf("(error)")

                # Search indexes
                search_node = coll_node.add("Search Indexes", data={"type": "search_group"})
                try:
                    search_indexes = await self.ctx.db_explorer.collection_search_indexes(
                        db_name, coll_name
                    )
                    if search_indexes:
                        for si in search_indexes:
                            si_name = si.get("name", "unnamed")
                            si_type = si.get("type", "search")
                            search_node.add_leaf(
                                f"{si_name} ({si_type})",
                                data={
                                    "type": "search_index",
                                    "db": db_name,
                                    "collection": coll_name,
                                    "name": si_name,
                                    "definition": si,
                                },
                            )
                    else:
                        search_node.add_leaf("(none)")
                except Exception:
                    search_node.add_leaf("(not available)")

    async def _refresh_direct(self, tree: Tree) -> None:
        """Populate tree using direct MongoDB access (server-local mode)."""
        client = self.ctx.mongo.client

        try:
            db_names = await client.list_database_names()
        except Exception:
            logger.debug("Could not list databases", exc_info=True)
            detail = self.query_one("#db-detail", RichLog)
            detail.clear()
            detail.write("Error listing databases. Check MongoDB connection.")
            return

        for db_name in sorted(db_names):
            db = client[db_name]
            db_node = tree.root.add(f"{db_name}", data={"type": "database", "name": db_name})

            try:
                coll_names = await db.list_collection_names()
            except Exception:
                logger.debug("Could not list collections for %s", db_name, exc_info=True)
                db_node.add_leaf("(error listing collections)")
                continue

            for coll_name in sorted(coll_names):
                coll = db[coll_name]
                try:
                    doc_count = await coll.estimated_document_count()
                except Exception:
                    doc_count = "?"

                coll_node = db_node.add(
                    f"{coll_name} ({doc_count} docs)",
                    data={
                        "type": "collection",
                        "db": db_name,
                        "name": coll_name,
                        "doc_count": doc_count,
                    },
                )

                # Standard indexes
                idx_node = coll_node.add("Indexes", data={"type": "indexes_group"})
                try:
                    indexes = await coll.index_information()
                    for idx_name, idx_info in sorted(indexes.items()):
                        unique = " (unique)" if idx_info.get("unique") else ""
                        idx_node.add_leaf(
                            f"{idx_name}{unique}",
                            data={
                                "type": "index",
                                "db": db_name,
                                "collection": coll_name,
                                "name": idx_name,
                                "info": idx_info,
                            },
                        )
                except Exception:
                    idx_node.add_leaf("(error)")

                # Atlas Search / Vector Search indexes
                search_node = coll_node.add("Search Indexes", data={"type": "search_group"})
                try:
                    result = await db.command({"listSearchIndexes": coll_name})
                    cursor = result.get("cursor", {})
                    search_indexes = cursor.get("firstBatch", [])
                    if search_indexes:
                        for si in search_indexes:
                            si_name = si.get("name", "unnamed")
                            si_type = si.get("type", "search")
                            search_node.add_leaf(
                                f"{si_name} ({si_type})",
                                data={
                                    "type": "search_index",
                                    "db": db_name,
                                    "collection": coll_name,
                                    "name": si_name,
                                    "definition": si,
                                },
                            )
                    else:
                        search_node.add_leaf("(none)")
                except Exception:
                    # listSearchIndexes requires Atlas or mongot — expected to fail locally
                    search_node.add_leaf("(not available)")

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Show details for the selected tree node."""
        node: TreeNode = event.node
        data = node.data
        detail = self.query_one("#db-detail", RichLog)
        detail.clear()

        if not data:
            detail.write(str(node.label))
            return

        node_type = data.get("type", "")

        if node_type == "database":
            detail.write(f"Database: {data['name']}")
            detail.write("")
            child_count = len(node.children) if hasattr(node, 'children') else 0
            detail.write(f"Collections: {child_count}")

        elif node_type == "collection":
            detail.write(f"Collection: {data['db']}.{data['name']}")
            detail.write(f"Estimated documents: {data.get('doc_count', '?')}")

        elif node_type == "index":
            info = data.get("info", {})
            detail.write(f"Index: {data['name']}")
            detail.write(f"Collection: {data['db']}.{data['collection']}")
            detail.write("")
            detail.write("Key specification:")
            for key_field, direction in info.get("key", []):
                detail.write(f"  {key_field}: {direction}")
            detail.write("")
            if info.get("unique"):
                detail.write("Unique: yes")
            if info.get("sparse"):
                detail.write("Sparse: yes")
            if info.get("expireAfterSeconds") is not None:
                detail.write(f"TTL: {info['expireAfterSeconds']}s")
            if info.get("partialFilterExpression"):
                detail.write(f"Partial filter: {json.dumps(info['partialFilterExpression'], indent=2)}")

        elif node_type == "search_index":
            definition = data.get("definition", {})
            detail.write(f"Search Index: {data['name']}")
            detail.write(f"Collection: {data['db']}.{data['collection']}")
            detail.write("")
            detail.write("Definition:")
            detail.write(json.dumps(definition, indent=2, default=str))

        else:
            detail.write(str(node.label))

    def action_refresh(self) -> None:
        self.run_worker(self._refresh())

    def action_pop_screen(self) -> None:
        self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()
