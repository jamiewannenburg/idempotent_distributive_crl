<?xml version="1.0"?>
<algebra>
  <basicAlgebra>
    <algName>model2</algName>
    <cardinality>3</cardinality>
    <universe>
      <elem>1</elem>
      <elem>0</elem>
      <elem>2</elem>
    </universe>
    <operations>
      <op>
        <opSymbol>
          <opName>*</opName>
          <arity>2</arity>
        </opSymbol>
        <opTable>
          <intArray>
            <row r="[0]">0,1,2</row>
            <row r="[1]">1,1,1</row>
            <row r="[2]">2,1,2</row>
          </intArray>
        </opTable>
      </op>
      <op>
        <opSymbol>
          <opName>\</opName>
          <arity>2</arity>
        </opSymbol>
        <opTable>
          <intArray>
            <row r="[0]">0,2,1</row>
            <row r="[1]">1,2,1</row>
            <row r="[2]">2,2,2</row>
          </intArray>
        </opTable>
      </op>
      <op>
        <opSymbol>
          <opName>e</opName>
          <arity>0</arity>
        </opSymbol>
        <opTable>
          <intArray>
            <row>0</row>
          </intArray>
        </opTable>
      </op>
    </operations>
  </basicAlgebra>
</algebra>
