"""
Program Name: DeterministicASTGraphExtractor
Description: A robust, memory-safe, and deterministic Abstract Syntax Tree 
            visitor that parses Python source code into structured nodes, 
            edges, and dependency import relations.
Version-Control-ID: b48e9c1f2a3d4e5f6a7b8c9d0e1f2a3b
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Set, Tuple

# =========================================================
# GRAPH INTERMEDIATE REPRESENTATION (IR)
# =========================================================

@dataclass(frozen=True)
class Node:
   """Represents a discrete symbol definition or import in the AST graph."""
   id: str
   kind: str
   file: str


@dataclass(frozen=True)
class Edge:
   """Represents a directional relationship (e.g., function call) between symbols."""
   src: str
   dst: str
   kind: str
   evidence: str


@dataclass
class Graph:
   """Encapsulates the full set of extracted nodes and edges."""
   nodes: Dict[str, Node]
   edges: List[Edge]


# =========================================================
# AST VISITOR ENGINE
# =========================================================

class GraphExtractor(ast.NodeVisitor):
   """Deterministic node visitor that walks Python source trees to extract IR maps."""
   
   def __init__(self, filename: str = "<module>") -> None:
       self.filename: str = filename
       self.nodes: Dict[str, Node] = {}
       self.edges: List[Edge] = []
       self.current_scope: List[str] = []
       self.defined: Set[str] = set()

   def add_node(self, name: str, kind: str) -> None:
       """Registers a unique node inside the graph dictionary if absent."""
       if name not in self.nodes:
           self.nodes[name] = Node(id=name, kind=kind, file=self.filename)

   def add_edge(self, src: str, dst: str, kind: str, evidence: str) -> None:
       """Appends a directional edge representing code relationships."""
       self.edges.append(Edge(src=src, dst=dst, kind=kind, evidence=evidence))

   def current_qualname(self, name: str) -> str:
       """Computes the fully qualified name based on current scope nesting."""
       if self.current_scope:
           return ".".join(self.current_scope + [name])
       return name

   def visit_Module(self, node: ast.Module) -> None:
       """Visits root module statements."""
       self.add_node(self.filename, "module")
       self.generic_visit(node)

   def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
       """Visits synchronous function definitions and scope levels."""
       qname = self.current_qualname(node.name)
       self.add_node(qname, "function")
       self.defined.add(qname)
       self.current_scope.append(node.name)
       self.generic_visit(node)
       self.current_scope.pop()

   def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
       """Visits asynchronous function definitions and scope levels."""
       qname = self.current_qualname(node.name)
       self.add_node(qname, "async_function")
       self.defined.add(qname)
       self.current_scope.append(node.name)
       self.generic_visit(node)
       self.current_scope.pop()

   def visit_ClassDef(self, node: ast.ClassDef) -> None:
       """Visits class declarations and nested member scope levels."""
       qname = self.current_qualname(node.name)
       self.add_node(qname, "class")
       self.defined.add(qname)
       self.current_scope.append(node.name)
       self.generic_visit(node)
       self.current_scope.pop()

   def visit_Call(self, node: ast.Call) -> None:
       """Visits expression call blocks to establish functional invocation edges."""
       caller = ".".join(self.current_scope) if self.current_scope else self.filename
       callee = self.resolve_call(node.func)

       if callee:
           self.add_edge(src=caller, dst=callee, kind="CALL", evidence=ast.unparse(node))
       self.generic_visit(node)

   def visit_Import(self, node: ast.Import) -> None:
       """Visits standard import declarations."""
       for alias in node.names:
           self.add_node(alias.name, "import")
       self.generic_visit(node)

   def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
       """Visits module 'from x import y' declarations."""
       module = node.module or ""
       for alias in node.names:
           full = f"{module}.{alias.name}" if module else alias.name
           self.add_node(full, "import")
       self.generic_visit(node)

   def resolve_call(self, func: ast.AST) -> Optional[str]:
       """Deterministically resolves direct name or chained attribute call targets."""
       if isinstance(func, ast.Name):
           return func.id
       if isinstance(func, ast.Attribute):
           return self.resolve_attr_chain(func)
       return None

   def resolve_attr_chain(self, node: ast.Attribute) -> str:
       """Safely reverses and constructs attribute sequences for method calls."""
       parts = []
       cur = node
       while isinstance(cur, ast.Attribute):
           parts.append(cur.attr)
           cur = cur.value
       if isinstance(cur, ast.Name):
           parts.append(cur.id)
       return ".".join(reversed(parts))


# =========================================================
# PUBLIC API WRAPPERS
# =========================================================

def extract_graph(source: str, filename: str = "<module>") -> Graph:
   """Parses raw Python code and extracts the structural relationship graph."""
   tree = ast.parse(source)
   extractor = GraphExtractor(filename=filename)
   extractor.visit(tree)
   return Graph(nodes=extractor.nodes, edges=extractor.edges)


def graph_to_dict(graph: Graph) -> dict:
   """Serializes the graph structure into a dictionary of nodes and edges."""