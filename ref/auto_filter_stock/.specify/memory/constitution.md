<!--
SYNC IMPACT REPORT
Version change: 0.0.0 → 1.0.0 (Initial constitution creation)
Modified principles: All new principles added
Added sections: 
  - Data Acquisition and Processing
  - Stock Screening and Momentum Scoring  
  - Visualization and Reporting
  - Governance (amendment procedures, versioning, compliance)
Removed sections: None
Templates requiring updates: 
  ✅ plan-template.md (constitution reference updated)
  ✅ spec-template.md (no changes needed)
  ✅ tasks-template.md (no changes needed)
Follow-up TODOs: None
-->

# Stock Screening System Constitution

## Core Principles

### I. Data Acquisition and Processing
Use pywencai library to obtain trading volume and heat data, ensuring stable and accurate data sources. Apply Min-Max normalization to both volume and heat data to ensure numerical values are within the same range for fair comparison. Utilize linear regression algorithms to calculate momentum scores, filtering out technically strongest stocks based on trend slope and R² values to assess stock price movements.

**Rationale**: Data is the foundation for screening strong stocks, ensuring accuracy, real-time capability, and consistency in data acquisition and processing workflows.

### II. Stock Screening and Momentum Scoring
Filter top 100 stocks by daily trading volume to ensure inclusion of capital-active stocks. Filter top 100 stocks by daily heat to ensure inclusion of market-attention stocks. After obtaining qualifying stocks through intersection, combine normalized scores for volume and heat, selecting top 30 stocks. Apply 25-day momentum scoring to further filter the top 30 stocks, selecting the top 10 stocks with strongest momentum.

**Rationale**: Multi-dimensional screening ensures selection of stocks with market capital support, high attention, and strong technical indicators.

### III. Visualization and Reporting
Generate dynamic K-line charts and momentum analysis graphs for screened strong stocks using Python. Create a webpage displaying all data where users can view detailed information for each stock including stock names, momentum analysis, and K-line charts. Support customizable display quantities for stocks, adjustable to 20, 30, etc. Enable one-click generation of all data and charts to avoid manual operations and improve user experience.

**Rationale**: Visualizing screening results provides users with intuitive analysis reports, simplifies review processes, and improves decision-making efficiency.

### IV. Test-First Implementation (NON-NEGOTIABLE)
TDD mandatory: Tests written → User approved → Tests fail → Then implement. Red-Green-Refactor cycle strictly enforced. All data processing algorithms must have comprehensive unit tests. Visualization components require integration tests. Momentum calculation accuracy must be validated against known benchmarks.

**Rationale**: Financial data processing demands absolute accuracy and reliability through comprehensive testing.

### V. Accuracy and Reliability Standards
All stock data must be validated for completeness and accuracy before processing. Momentum calculations must handle edge cases including missing data, suspended trading, and stock splits. Error handling must provide clear feedback for data source failures. Performance monitoring required for real-time data processing pipelines.

**Rationale**: Financial systems require high reliability and accurate data processing to ensure investment decisions are based on valid information.

## Data Quality and Performance Standards

### Data Validation Requirements
- Real-time data feeds must be validated within 5 seconds of receipt
- Historical data must maintain 99.9% completeness for momentum calculations
- Data anomalies must be flagged and logged for manual review
- Backup data sources must be available for primary feed failures

### Performance Targets
- Screen 5000+ stocks within 2 minutes during market hours
- Generate visualization reports within 30 seconds for 30 stocks
- Support concurrent users: minimum 50 simultaneous report requests
- Memory usage: maximum 2GB during full screening process

### Error Handling and Monitoring
- Data source failures must trigger automatic fallback procedures
- All calculation errors must be logged with timestamp and stock symbol
- System health metrics must be available via monitoring dashboard
- Alert notifications for data quality issues within 1 minute

## Development Workflow and Quality Gates

### Code Review Requirements
All pull requests must include unit tests for data processing algorithms. Integration tests required for visualization components. Performance benchmarks must be included for screening algorithms. Security review mandatory for any data access modifications.

### Testing Gates
Unit test coverage must exceed 90% for data processing modules. Integration tests must cover all visualization endpoints. Performance tests required for screening throughput benchmarks. Data accuracy tests must validate against historical known results.

### Deployment Approval Process
Staging environment must pass all data accuracy validations. Production deployment requires sign-off from data quality team. Rollback procedures must be tested before each release. Monitoring alerts must be configured before deployment.

## Governance

### Amendment Procedures
This constitution shall be updated with version increments and revision content documented in version management. Each revision requires comprehensive review ensuring all updates align with project core objectives and principles. Amendment proposals must include impact analysis on existing screening algorithms and data processing workflows.

### Version Management
Version numbers follow semantic versioning (SemVer) rules:
- MAJOR version: Incompatible changes to principles or governance structure
- MINOR version: Addition of new principles, features, or clauses
- PATCH version: Text refinements or revisions to existing clauses

### Compliance Review
All principles and clauses must be regularly reviewed to ensure compliance with industry standards and best practices. The project must establish internal audit mechanisms to ensure compliance and efficient execution. Quarterly reviews required for data accuracy standards and performance benchmarks.

**Version**: 1.0.0 | **Ratified**: 2025-10-07 | **Last Amended**: 2025-10-07