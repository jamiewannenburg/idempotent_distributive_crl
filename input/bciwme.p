% Enabling option dependencies (ignore applies only on input).

% The LADR formulas contain function or predicate symbols
% that are not legal TPTP symbols, and we have replaced those
% symbols with new symbols.  Here is the list of the unaccepted
% symbols and the corresponding replacements.
%
%   (arity 2)        \    tptp0
%   (arity 2)       <=    tptp1

cnf(sos,axiom,tptp1(A,A)).
fof(sos,axiom,! [X0] : ! [X1] : ! [X2] : ((tptp1(X0,X1) & tptp1(X1,X2)) => tptp1(X0,X2))).
fof(sos,axiom,! [X3] : ! [X4] : ((tptp1(X3,X4) & tptp1(X4,X3)) => X3 = X4)).
cnf(sos,axiom,tptp1(tptp0(A,B),tptp0(tptp0(B,C),tptp0(A,C)))).
cnf(sos,axiom,tptp0(A,tptp0(B,C)) = tptp0(B,tptp0(A,C))).
fof(sos,axiom,! [X5] : ! [X6] : (tptp1(tptp0(X5,X5),X6) => tptp1(tptp0(X6,X6),X6))).
fof(sos,axiom,! [X7] : ! [X8] : (tptp1(X7,X8) <=> tptp0(X7,X8) = tptp0(tptp0(X7,X8),tptp0(X7,X8)))).
cnf(sos,axiom,tptp1(A,tptp0(tptp0(A,B),B))).
cnf(sos,axiom,e = tptp0(e,e)).
cnf(sos,axiom,tptp1(e,tptp0(A,A))).
cnf(sos,axiom,tptp0(e,A) = A).
fof(sos,axiom,! [X9] : ! [X10] : (tptp1(X9,X10) <=> tptp1(e,tptp0(X9,X10)))).
cnf(sos,axiom,tptp1(tptp0(A,tptp0(A,B)),tptp0(A,B))).
cnf(sos,axiom,tptp1(A,tptp0(A,A))).
cnf(sos,axiom,tptp1(tptp0(A,B),tptp0(A,tptp0(A,B)))).
fof(goals,conjecture,! [X11] : tptp0(tptp0(tptp0(X11,e),e),X11) = tptp0(tptp0(tptp0(tptp0(tptp0(tptp0(tptp0(tptp0(tptp0(X11,e),e),X11),e),e),X11),e),e),X11)).
