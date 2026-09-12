use std::fs;
use std::path::Path;

use syn::visit::Visit;

use crate::error::Result;

#[derive(Default)]
struct SourcePolicy {
    asynchronous: bool,
}

impl<'ast> Visit<'ast> for SourcePolicy {
    fn visit_signature(&mut self, signature: &'ast syn::Signature) {
        self.asynchronous |= signature.asyncness.is_some();
        syn::visit::visit_signature(self, signature);
    }

    fn visit_expr_async(&mut self, expression: &'ast syn::ExprAsync) {
        self.asynchronous = true;
        syn::visit::visit_expr_async(self, expression);
    }

    fn visit_expr_await(&mut self, expression: &'ast syn::ExprAwait) {
        self.asynchronous = true;
        syn::visit::visit_expr_await(self, expression);
    }

    fn visit_expr_closure(&mut self, expression: &'ast syn::ExprClosure) {
        self.asynchronous |= expression.asyncness.is_some();
        syn::visit::visit_expr_closure(self, expression);
    }

    fn visit_macro(&mut self, value: &'ast syn::Macro) {
        self.asynchronous |= has_async_keyword(value.tokens.clone());
    }
}

fn has_async_keyword(tokens: proc_macro2::TokenStream) -> bool {
    tokens.into_iter().any(|token| match token {
        proc_macro2::TokenTree::Ident(identifier) => identifier == "async" || identifier == "await",
        proc_macro2::TokenTree::Group(group) => has_async_keyword(group.stream()),
        proc_macro2::TokenTree::Punct(_) | proc_macro2::TokenTree::Literal(_) => false,
    })
}

pub fn check(root: &Path) -> Result<usize> {
    let mut files = 0;
    for directory in ["crates", "tools"] {
        files += visit_directory(&root.join(directory))?;
    }
    Ok(files)
}

fn visit_directory(directory: &Path) -> Result<usize> {
    let mut files = 0;
    for entry in fs::read_dir(directory)? {
        let entry = entry?;
        let path = entry.path();
        if entry.file_type()?.is_dir() {
            files += visit_directory(&path)?;
        } else if path.extension().is_some_and(|extension| extension == "rs") {
            check_source(&path)?;
            files += 1;
        }
    }
    Ok(files)
}

fn check_source(path: &Path) -> Result<()> {
    let source = fs::read_to_string(path)?;
    let syntax = syn::parse_file(&source)?;
    let mut policy = SourcePolicy::default();
    policy.visit_file(&syntax);
    if policy.asynchronous {
        return Err(format!("Asynchronous Rust code is prohibited: {}", path.display()).into());
    }
    Ok(())
}
