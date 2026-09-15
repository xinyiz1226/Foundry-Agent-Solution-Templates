-- PROPOSED ONLY: not deployed or executed by the local preparation/analysis tools.
-- Target: an existing AdventureWorksDW database, after explicit deployment approval.
-- Prerequisite: dbo.DimCurrency must map CurrencyKey=100 to USD / US Dollar,
-- matching data/adventureworks-manifest.json. No currency conversion is performed.
-- This view intentionally preserves all dates in the selected currency scope;
-- approved analysis coverage is supplied separately as exclusive-end intervals.
--
-- SEPARATE MANUAL APPROVAL: if reporting does not exist, a database owner may
-- choose to run the following independently. It is deliberately commented out:
-- IF SCHEMA_ID(N'reporting') IS NULL
--     EXEC(N'CREATE SCHEMA [reporting] AUTHORIZATION [dbo]');
-- No users, grants, identities, networks, databases or other resources are created.

CREATE OR ALTER VIEW [reporting].[v_internet_sales]
AS
SELECT
    CAST([dd].[FullDateAlternateKey] AS date) AS [order_date],
    [fis].[SalesOrderNumber] AS [sales_order_number],
    [fis].[ProductKey] AS [product_id],
    [dp].[EnglishProductName] AS [product_name],
    [fis].[SalesTerritoryKey] AS [territory_id],
    [dst].[SalesTerritoryRegion] AS [territory_name],
    CAST([fis].[SalesAmount] AS decimal(19,4)) AS [sales_amount],
    CAST([fis].[TotalProductCost] AS decimal(19,4)) AS [total_product_cost]
FROM [dbo].[FactInternetSales] AS [fis]
INNER JOIN [dbo].[DimDate] AS [dd]
    ON [dd].[DateKey] = [fis].[OrderDateKey]
INNER JOIN [dbo].[DimProduct] AS [dp]
    ON [dp].[ProductKey] = [fis].[ProductKey]
INNER JOIN [dbo].[DimSalesTerritory] AS [dst]
    ON [dst].[SalesTerritoryKey] = [fis].[SalesTerritoryKey]
WHERE [fis].[CurrencyKey] = 100;
