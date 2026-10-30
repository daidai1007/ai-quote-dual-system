export const registerContractSql=(kind,alias,principal,q)=>
  `calc.register_generated_contract(${q(kind)},${alias}.record_id,${q(principal.identityMode||'AUTHENTICATED')})`;
export const contractSchemeSql=(kind,record,q)=>`(SELECT jsonb_build_object('scheme_no',s.scheme_no,'status',s.status,
  'lock_version',s.lock_version,'version_no',s.version_no,'source_kind',s.source_kind,'contract_record_id',l.contract_record_id)
  FROM calc.quote_scheme_contract_link l JOIN calc.quote_scheme s USING(scheme_id)
  WHERE l.source_kind=${q(kind)} AND l.contract_record_id=${record})`;
