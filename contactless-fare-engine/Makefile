.PHONY: build test format run simulate

build:
	dotnet restore && dotnet build --no-restore -c Release -warnaserror

test: build
	dotnet test --no-build -c Release

format:
	dotnet format

run:
	dotnet run --project src/FareEngine.Api

simulate:
	dotnet run -c Release --project src/FareEngine.Simulator -- 2000 4 42
